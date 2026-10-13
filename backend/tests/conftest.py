import hashlib
import json
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
    with GraphDatabase.driver(settings.neo4j_uri,
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
