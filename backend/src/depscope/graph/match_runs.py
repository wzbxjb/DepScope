from depscope.analysis.matching import Finding, MatchRun
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import Page, decode_cursor, encode_cursor, now, page_limit
from depscope.sources.advisories import AdvisoryRevision


class MatchRunRepository:
    def __init__(self,driver):
        self.driver=driver

    def save(self,runs: tuple[MatchRun,...],revisions: tuple[AdvisoryRevision,...]) -> None:
        def persist(tx):
            for revision in revisions:
                row=tx.run("""
                    MERGE (a:AdvisoryRevision {revision_id:$key})
                    ON CREATE SET a.id=$id,a.modified=$modified,a.digest=$digest,a.payload=$payload,
                                  a.withdrawn=$withdrawn
                    RETURN a.payload AS payload
                    """,key=revision.revision_id,id=revision.id,modified=revision.modified,
                    digest=revision.digest,payload=revision.model_dump_json(),withdrawn=revision.withdrawn).single()
                stored=AdvisoryRevision.model_validate_json(row["payload"])
                if stored.model_dump(exclude={"source"}) != revision.model_dump(exclude={"source"}):
                    raise DomainError("ADVISORY_IMMUTABLE", "Advisory revision cannot be modified")
                tx.run("""
                    MATCH (a:AdvisoryRevision {revision_id:$key})
                    UNWIND $ids AS id
                    MERGE (i:Identifier {id:id})
                    MERGE (a)-[:HAS_IDENTIFIER]->(i)
                    """,key=revision.revision_id,ids=list(dict.fromkeys((revision.id,)+revision.aliases))).consume()
                tx.run("MATCH (a:AdvisoryRevision {revision_id:$key}) MERGE (source:SourceRecord {digest:$digest}) MERGE (a)-[:DERIVED_FROM]->(source)",key=revision.revision_id,digest=revision.digest).consume()
            for run in runs:
                row=tx.run("MATCH (s:Snapshot {snapshot_id:$sid,status:'ready'}) RETURN s.project_id AS project",sid=run.snapshot_id).single()
                if row is None:
                    raise DomainError("SNAPSHOT_NOT_READY", "Match run requires a published snapshot")
                existing=tx.run("MATCH (r:MatchRun {id:$id}) RETURN r.payload AS payload",id=run.id).single()
                if existing:
                    if existing["payload"] != run.model_dump_json():
                        raise DomainError("MATCH_RUN_IMMUTABLE", "Match runs cannot be modified")
                    continue
                tx.run("""
                    MATCH (s:Snapshot {snapshot_id:$sid,status:'ready'})
                    CREATE (r:MatchRun {id:$id,snapshot_id:$sid,project_id:$project,
                           collection_id:$collection,observed_at:$time,payload:$payload,status:'ready'})
                    CREATE (r)-[:FOR_SNAPSHOT]->(s)
                    """,sid=run.snapshot_id,id=run.id,project=row["project"],collection=run.collection_id,
                    time=run.observed_at,payload=run.model_dump_json()).consume()
                for finding in run.findings:
                    count=tx.run("""
                        MATCH (r:MatchRun {id:$run}),(c:ComponentInstance {inst_key:$instance,snapshot_id:$sid})
                        CREATE (f:Finding {id:$id,instance_id:$instance,group_id:$group,status:$status,payload:$payload})
                        CREATE (r)-[:HAS_FINDING]->(f)
                        CREATE (f)-[:FOR_INSTANCE]->(c)
                        RETURN count(f) AS n
                        """,run=run.id,sid=run.snapshot_id,id=finding.id,instance=finding.instance_id,
                        group=finding.group_id,status=finding.status,payload=finding.model_dump_json()).single()["n"]
                    if count != 1:
                        raise DomainError("FINDING_CONTEXT_MISMATCH", "Finding instance must belong to its run snapshot")
                    count=tx.run("""
                        MATCH (f:Finding {id:$id})
                        UNWIND $revisions AS revision
                        MATCH (a:AdvisoryRevision {revision_id:revision})
                        CREATE (f)-[:SUPPORTED_BY]->(a)
                        RETURN count(a) AS n
                        """,id=finding.id,revisions=list(finding.revision_ids)).single()["n"]
                    if count != len(finding.revision_ids):
                        raise DomainError("FINDING_EVIDENCE_MISSING", "Finding requires every advisory revision")
        with self.driver.session() as session:
            session.execute_write(persist)

    def load(self,id: str) -> MatchRun:
        with self.driver.session() as session:
            row=session.run("MATCH (r:MatchRun {id:$id,status:'ready'}) RETURN r.payload AS payload",id=id).single()
        if row is None:
            raise DomainError("MATCH_RUN_NOT_FOUND", "Match run is unavailable")
        return MatchRun.model_validate_json(row["payload"])

    def latest(self,snapshot_id: str) -> MatchRun:
        with self.driver.session() as session:
            row=session.run("MATCH (r:MatchRun {snapshot_id:$sid,status:'ready'}) RETURN r.id AS id ORDER BY r.observed_at DESC,r.id DESC LIMIT 1",sid=snapshot_id).single()
        if row is None:
            raise DomainError("MATCH_RUN_NOT_FOUND", "Snapshot has no completed match run")
        return self.load(row["id"])

    def revision(self,id: str) -> AdvisoryRevision:
        with self.driver.session() as session:
            row=session.run("MATCH (a:AdvisoryRevision {revision_id:$id}) RETURN a.payload AS payload",id=id).single()
        if row is None:
            raise DomainError("ADVISORY_NOT_FOUND", "Advisory revision is unavailable")
        return AdvisoryRevision.model_validate_json(row["payload"])

    def finding(self,id: str) -> tuple[Finding,MatchRun]:
        with self.driver.session() as session:
            row=session.run("MATCH (r:MatchRun)-[:HAS_FINDING]->(f:Finding {id:$id}) RETURN f.payload AS payload,r.id AS run",id=id).single()
        if row is None:
            raise DomainError("FINDING_NOT_FOUND", "Finding is unavailable")
        return Finding.model_validate_json(row["payload"]),self.load(row["run"])

    def list_runs(self,snapshot_id,cursor=None,limit=50) -> Page:
        scope="runs:"+snapshot_id
        last=decode_cursor(cursor,scope)
        limit=page_limit(limit)
        with self.driver.session() as session:
            rows=tuple(row.data() for row in session.run("MATCH (r:MatchRun {snapshot_id:$sid,status:'ready'}) WHERE r.id>$last RETURN r.id AS id,r.collection_id AS collection_id,r.observed_at AS observed_at ORDER BY r.id LIMIT $limit",sid=snapshot_id,last=last,limit=limit+1))
        cursor=encode_cursor(scope,rows[limit-1]["id"]) if len(rows)>limit else None
        return Page(items=rows[:limit],next_cursor=cursor,observed_at=now())

    def list_findings(self,run_id,cursor=None,limit=50) -> Page:
        run=self.load(run_id)
        scope="findings:"+run.id
        last=decode_cursor(cursor,scope)
        limit=page_limit(limit)
        values=tuple(f.model_dump(mode="json") for f in sorted(run.findings,key=lambda f:f.id) if f.id>last)
        selected_ids=[row["id"] for row in values[:limit]]
        with self.driver.session() as session:
            context={row["id"]:row.data() for row in session.run("MATCH (f:Finding)-[:FOR_INSTANCE]->(c:ComponentInstance {snapshot_id:$sid}) WHERE f.id IN $ids OPTIONAL MATCH (c)-[:INSTANCE_OF]->(p:PackageVersion) OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(a:AdvisoryRevision) RETURN f.id AS id,c.name AS component_name,p.name AS package_name,c.raw_version AS raw_version,collect(a.id) AS advisory_ids",sid=run.snapshot_id,ids=selected_ids)}
        values=tuple(row | context.get(row["id"],{}) for row in values)
        cursor=encode_cursor(scope,values[limit-1]["id"]) if len(values)>limit else None
        return Page(items=values[:limit],next_cursor=cursor,observed_at=run.observed_at)
