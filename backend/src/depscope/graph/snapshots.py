"""Context-isolated graph persistence with owned staging and immutable publication."""
import hashlib
import uuid

from depscope.identity.coordinates import instance_key, snapshot_key
from depscope.ingest.models import Snapshot
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import Page, decode_cursor, encode_cursor, now, page_limit


class SnapshotRepository:
    def __init__(self, driver):
        self.driver = driver

    def create_project(self, name: str, kind: str = "user_project") -> str:
        name = name.strip()
        if not name or len(name) > 200:
            raise DomainError("INVALID_PROJECT", "Project name must contain 1 to 200 characters")
        project_id = str(uuid.uuid4())
        with self.driver.session() as session:
            session.run("CREATE (:Project {id:$id,name:$name,kind:$kind,created_at:$time})",
                        id=project_id,name=name,kind=kind,time=now()).consume()
        return project_id

    def list_projects(self, cursor=None, limit=50) -> Page:
        last = decode_cursor(cursor,"projects")
        limit = page_limit(limit)
        with self.driver.session() as session:
            items = tuple(dict(row["p"]) for row in session.run(
                "MATCH (p:Project) WHERE p.id > $last RETURN p ORDER BY p.id LIMIT $limit",
                last=last,limit=limit+1))
        next_cursor = encode_cursor("projects",items[limit-1]["id"]) if len(items)>limit else None
        return Page(items=items[:limit],next_cursor=next_cursor,observed_at=now())

    def stage(self, snapshot: Snapshot, job_id: str) -> bool:
        expected = snapshot_key(snapshot.project_id,snapshot.source_kind,snapshot.source.digest)
        if snapshot.snapshot_id != expected:
            raise DomainError("SNAPSHOT_ID_MISMATCH", "Snapshot identity must match its source context")
        def claim(tx):
            if tx.run("MATCH (p:Project {id:$p}) RETURN p.id AS id",p=snapshot.project_id).single() is None:
                raise DomainError("PROJECT_NOT_FOUND", "Project is unavailable")
            row = tx.run("""
                MERGE (s:Snapshot {snapshot_id:$sid})
                ON CREATE SET s.project_id=$p,s.status='writing',s.owner_job_id=$job,
                              s.payload=$payload,s.observed_at=$time,s.source_kind=$kind,
                              s.component_count=$nodes,s.edge_count=$edges
                RETURN s.status AS status,s.owner_job_id AS owner,s.payload AS payload
                """,sid=snapshot.snapshot_id,p=snapshot.project_id,job=job_id,
                payload=snapshot.model_dump_json(),time=snapshot.source.observed_at,
                kind=snapshot.source_kind,nodes=len(snapshot.components),edges=len(snapshot.edges)).single()
            if row["status"] == "ready":
                return False
            if row["owner"] != job_id:
                raise DomainError("SNAPSHOT_BUSY", "Another task owns the unpublished snapshot",retryable=True)
            if row["payload"] != snapshot.model_dump_json():
                raise DomainError("SNAPSHOT_IMMUTABLE", "A staged snapshot cannot change its content")
            return True
        with self.driver.session() as session:
            if not session.execute_write(claim):
                return False
            for start in range(0,len(snapshot.components),500):
                rows=[]
                for component in snapshot.components[start:start+500]:
                    coordinate=component.coordinate
                    rows.append({"local_id":component.local_id,"inst_key":instance_key(snapshot.snapshot_id,component.local_id),
                                 "name":component.name,"known":component.dependencies_known,
                                 "pointer":component.pointer,"package":coordinate.key if coordinate else None,
                                 "ecosystem":coordinate.ecosystem if coordinate else None,
                                 "package_name":coordinate.name if coordinate else None,
                                 "version":coordinate.version if coordinate else None,
                                 "raw_version":coordinate.raw_version if coordinate else None})
                count=session.run("""
                    MATCH (s:Snapshot {snapshot_id:$sid,status:'writing',owner_job_id:$job})
                    UNWIND $rows AS row
                    MERGE (c:ComponentInstance {inst_key:row.inst_key})
                    SET c.snapshot_id=$sid,c.project_id=$p,c.local_id=row.local_id,c.name=row.name,
                        c.dependencies_known=row.known,c.pointer=row.pointer,c.raw_version=row.raw_version
                    MERGE (s)-[:CONTAINS]->(c)
                    FOREACH (_ IN CASE WHEN row.package IS NULL THEN [] ELSE [1] END |
                        MERGE (v:PackageVersion {key:row.package})
                        ON CREATE SET v.ecosystem=row.ecosystem,v.name=row.package_name,v.version=row.version
                        MERGE (c)-[:INSTANCE_OF]->(v))
                    RETURN count(c) AS n
                    """,sid=snapshot.snapshot_id,job=job_id,p=snapshot.project_id,rows=rows).single()["n"]
                if count != len(rows):
                    raise DomainError("STAGE_INTERRUPTED", "Component staging no longer owns its snapshot")
            for start in range(0,len(snapshot.edges),500):
                rows=[{"from":edge.from_id,"to":edge.to_id,"requirement":edge.requirement,
                       "pointer":edge.pointer,"key":hashlib.sha256((snapshot.snapshot_id+":"+edge.pointer).encode()).hexdigest()}
                      for edge in snapshot.edges[start:start+500]]
                count=session.run("""
                    MATCH (s:Snapshot {snapshot_id:$sid,status:'writing',owner_job_id:$job})
                    UNWIND $rows AS row
                    MATCH (a:ComponentInstance {snapshot_id:$sid,local_id:row.from})
                    MATCH (b:ComponentInstance {snapshot_id:$sid,local_id:row.to})
                    MERGE (a)-[e:DEPENDS_ON {edge_key:row.key}]->(b)
                    SET e.requirement=row.requirement,e.pointer=row.pointer
                    RETURN count(e) AS n
                    """,sid=snapshot.snapshot_id,job=job_id,rows=rows).single()["n"]
                if count != len(rows):
                    raise DomainError("STAGE_INTERRUPTED", "Edge staging failed context validation")
        return True

    def publish(self, snapshot: Snapshot, job_id: str) -> str:
        try:
            if not self.stage(snapshot,job_id):
                return snapshot.snapshot_id
            def finalize(tx):
                node_count=tx.run("MATCH (s:Snapshot {snapshot_id:$sid,status:'writing',owner_job_id:$job})-[:CONTAINS]->(c) RETURN count(c) AS n",
                                  sid=snapshot.snapshot_id,job=job_id).single()["n"]
                edge_count=tx.run("MATCH (a:ComponentInstance {snapshot_id:$sid})-[e:DEPENDS_ON]->(b:ComponentInstance {snapshot_id:$sid}) RETURN count(e) AS n",
                                  sid=snapshot.snapshot_id).single()["n"]
                if node_count != len(snapshot.components) or edge_count != len(snapshot.edges):
                    raise DomainError("STAGE_COUNTS_MISMATCH", "Graph counts differ from validated source")
                tx.run("""
                    MATCH (p:Project {id:$p}),(s:Snapshot {snapshot_id:$sid,status:'writing',owner_job_id:$job})
                    MERGE (p)-[:HAS_SNAPSHOT]->(s)
                    MERGE (source:SourceRecord {digest:$digest})
                    MERGE (s)-[:DERIVED_FROM]->(source)
                    SET s.status='ready',s.published_at=$time
                    """,p=snapshot.project_id,sid=snapshot.snapshot_id,job=job_id,
                    digest=snapshot.source.digest,time=now()).consume()
                if snapshot.root_id is not None:
                    tx.run("MATCH (s:Snapshot {snapshot_id:$sid}),(r:ComponentInstance {snapshot_id:$sid,local_id:$root}) MERGE (s)-[:HAS_ROOT]->(r)",
                           sid=snapshot.snapshot_id,root=snapshot.root_id).consume()
            with self.driver.session() as session:
                session.execute_write(finalize)
            return snapshot.snapshot_id
        except Exception:
            self.delete_unpublished(job_id)
            raise

    def load(self, snapshot_id: str) -> Snapshot:
        with self.driver.session() as session:
            row=session.run("MATCH (s:Snapshot {snapshot_id:$sid}) RETURN s.status AS status,s.payload AS payload",sid=snapshot_id).single()
        if row is None:
            raise DomainError("SNAPSHOT_NOT_FOUND", "Snapshot is unavailable")
        if row["status"] != "ready":
            raise DomainError("SNAPSHOT_NOT_READY", "Snapshot has not been published")
        return Snapshot.model_validate_json(row["payload"])

    def delete_unpublished(self, job_id: str) -> int:
        def cleanup(tx):
            rows=list(tx.run("MATCH (s:Snapshot {owner_job_id:$job,status:'writing'}) RETURN s.snapshot_id AS sid",job=job_id))
            for row in rows:
                tx.run("MATCH (c:ComponentInstance {snapshot_id:$sid}) DETACH DELETE c",sid=row["sid"]).consume()
                tx.run("MATCH (s:Snapshot {snapshot_id:$sid,owner_job_id:$job,status:'writing'}) DETACH DELETE s",sid=row["sid"],job=job_id).consume()
            return len(rows)
        with self.driver.session() as session:
            return session.execute_write(cleanup)

    def list_snapshots(self, project_id: str, cursor=None, limit=50) -> Page:
        last=decode_cursor(cursor,"snapshots:"+project_id)
        limit=page_limit(limit)
        with self.driver.session() as session:
            rows=tuple(dict(row["s"]) for row in session.run("MATCH (s:Snapshot {project_id:$p,status:'ready'}) WHERE s.snapshot_id > $last RETURN s ORDER BY s.snapshot_id LIMIT $limit",
                       p=project_id,last=last,limit=limit+1))
        items=tuple({key:value for key,value in row.items() if key not in ("payload","owner_job_id")} for row in rows[:limit])
        cursor=encode_cursor("snapshots:"+project_id,items[-1]["snapshot_id"]) if len(rows)>limit else None
        return Page(items=items,next_cursor=cursor,observed_at=now())
