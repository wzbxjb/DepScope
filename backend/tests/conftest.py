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
