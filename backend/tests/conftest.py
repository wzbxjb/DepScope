import hashlib
import json
import os
from pathlib import Path

import pytest

from depscope.identity.coordinates import snapshot_key
from depscope.ingest.models import Component, Edge, Snapshot, SourceRef


@pytest.fixture
def source_for():
    def build(raw: bytes) -> SourceRef:
        return SourceRef(uri="fixture://constructed", digest=hashlib.sha256(raw).hexdigest(),
                         observed_at="2026-10-13T00:00:00Z", parser_version="test-v1")
    return build


@pytest.fixture
def research_dir():
    return Path(__file__).resolve().parents[2] / "docs/research/software_supply_chain"


@pytest.fixture
def snapshot_factory(source_for):
    def build(project, local_ids, edge_pairs, root=None):
        raw = json.dumps([project, local_ids, edge_pairs, root]).encode()
        source = source_for(raw)
        return Snapshot(snapshot_id=snapshot_key(project, "constructed", source.digest),
                        project_id=project, source_kind="constructed", source=source,
                        components=tuple(Component(local_id=i, name=i, coordinate=None,
                                         dependencies_known=True, pointer=f"/components/{n}")
                                         for n, i in enumerate(local_ids)),
                        edges=tuple(Edge(from_id=a, to_id=b, pointer=f"/edges/{n}")
                                    for n, (a,b) in enumerate(edge_pairs)),
                        root_id=root, environment={}, issues=())
    return build


@pytest.fixture
def driver():
    from neo4j import GraphDatabase

    from depscope.runtime.config import load_settings
    settings = load_settings()
    with GraphDatabase.driver(os.environ.get("DEPSCOPE_TEST_NEO4J_URI","bolt://127.0.0.1:17688"),
                              auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value())) as db:
        db.verify_connectivity()
        yield db


@pytest.fixture
def repo(driver):
    from depscope.graph.migrations import migrate
    from depscope.graph.snapshots import SnapshotRepository
    migrate(driver)
    repository = SnapshotRepository(driver)
    original = repository.create_project
    owned = []
    def create(name, kind="user_project"):
        project = original("test-only:" + name, kind)
        owned.append(project)
        return project
    repository.create_project = create
    yield repository
    # Only these random test-owned project contexts; no shared PackageVersion deletion.
    with driver.session() as session:
        for project in owned:
            session.run("MATCH (c:Comparison)-[:BASELINE|CANDIDATE]->(s:Snapshot {project_id:$p}) DETACH DELETE c", p=project).consume()
            session.run("MATCH (r:MatchRun {project_id:$p})-[:HAS_FINDING]->(f) DETACH DELETE f", p=project).consume()
            session.run("MATCH (r:MatchRun {project_id:$p}) DETACH DELETE r", p=project).consume()
            session.run("MATCH (c:ComponentInstance {project_id:$p}) DETACH DELETE c", p=project).consume()
            session.run("MATCH (s:Snapshot {project_id:$p}) DETACH DELETE s", p=project).consume()
            session.run("MATCH (p:Project {id:$p}) DETACH DELETE p", p=project).consume()


@pytest.fixture
def public_snapshot_factory(research_dir, source_for):
    from depscope.ingest.depsdev import parse_depsdev
    def build(project):
        raw = (research_dir / "experimental_dependencies.json").read_bytes()
        return parse_depsdev(raw, project, source_for(raw))
    return build


@pytest.fixture
def job_store(driver):
    from depscope.graph.migrations import migrate
    from depscope.jobs.store import JobStore
    migrate(driver)
    store = JobStore(driver)
    created=[]
    original=store.enqueue
    def enqueue(kind,payload):
        job=original(kind,payload)
        created.append(job.id)
        return job
    store.enqueue=enqueue
    yield store
    with driver.session() as session:
        session.run("MATCH (j:Job) WHERE j.id IN $ids DETACH DELETE j",ids=created).consume()
        session.run("MATCH (l:MutationLease) WHERE l.job_id IN $ids SET l.owner_token=null,l.job_id=null,l.heartbeat=null",ids=created).consume()


@pytest.fixture
def ready_snapshot(repo,public_snapshot_factory):
    snapshot=public_snapshot_factory(repo.create_project("ready"))
    repo.publish(snapshot,"fixture-ready")
    return snapshot


@pytest.fixture
async def mock_osv(respx_mock,tmp_path):
    from helpers.osv import MockOsv
    mock=MockOsv(respx_mock,tmp_path)
    yield mock
    await mock.http.aclose()


@pytest.fixture
def advisory_factory(source_for):
    from depscope.sources.advisories import AdvisoryRevision
    def create(id,aliases=(),related=(),withdrawn=None):
        doc={"id":id,"modified":"2026-10-13T00:00:00Z","aliases":list(aliases),
             "related":list(related),"withdrawn":withdrawn,
             "affected":[{"package":{"ecosystem":"PyPI","name":"requests"}}],
             "summary":"Constructed test advisory","details":"Unit-test-only evidence"}
        raw=json.dumps(doc).encode()
        source=source_for(raw)
        return AdvisoryRevision(id=id,modified=doc["modified"],digest=source.digest,
                    aliases=aliases,related=related,withdrawn=withdrawn,affected=tuple(doc["affected"]),
                    summary=doc["summary"],details=doc["details"],source=source)
    return create


@pytest.fixture
def comparison_inputs(source_for):
    from depscope.analysis.matching import Finding, MatchRun
    from depscope.identity.coordinates import identify, instance_key
    from depscope.sources.advisories import PackageQuery
    def create(before_status,after_status):
        snapshots=[]
        runs=[]
        for index,status in enumerate((before_status,after_status)):
            raw=json.dumps({"kind":"constructed-comparison","index":index}).encode()
            source=source_for(raw)
            sid=snapshot_key("comparison","constructed",source.digest)
            coordinate=identify("requests","2.31.0" if index==0 else "2.32.3",None)
            component=Component(local_id="r",name="requests",coordinate=coordinate,dependencies_known=True,pointer="/components/0")
            snapshot=Snapshot(snapshot_id=sid,project_id="comparison",source_kind="constructed",source=source,
                              components=(component,),edges=(),root_id="r",environment={},issues=())
            findings=(Finding(id="f"+str(index),instance_id=instance_key(sid,"r"),group_id="group-a",revision_ids=("a"*64,)),) if status=="matched" else ()
            run=MatchRun(id="run-"+str(index),snapshot_id=sid,collection_id="shared",observed_at="2026-10-13T00:00:00Z",
                         queries=(PackageQuery(coordinate=coordinate,status=status,record_ids=("GHSA-a",) if findings else (),source_refs=(source,)),),
                         findings=findings,revision_ids=("a"*64,) if findings else (),coverage={"total":1,"confirmed":int(status in ("matched","no_match")),"unknown":int(status not in ("matched","no_match"))})
            snapshots.append(snapshot)
            runs.append(run)
        return runs[0],runs[1],snapshots[0],snapshots[1]
    return create


@pytest.fixture
def ledger(driver):
    import uuid
    from depscope.generation.budget import BudgetLedger
    instance=BudgetLedger(driver)
    instance.test_run="test-budget:"+uuid.uuid4().hex
    yield instance
    with driver.session() as session:
        session.run("MATCH (b:GenerationBudget {id:$id}) OPTIONAL MATCH (b)-[:HAS_CALL]->(c) DETACH DELETE c,b",id=instance.test_run).consume()
