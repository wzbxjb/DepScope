import pytest
from pydantic import ValidationError

from depscope.identity.coordinates import identify
from depscope.ingest.models import Component, Edge, Snapshot, SourceRef


def make_snapshot(**updates):
    values = dict(snapshot_id="a"*64, project_id="p", source_kind="constructed",
                  source=SourceRef(uri="fixture://constructed", digest="b"*64,
                                   observed_at="2026-10-13T00:00:00Z", parser_version="test-v1"),
                  components=(Component(local_id="r", name="root", coordinate=None,
                                        dependencies_known=False, pointer="/root"),),
                  edges=(), root_id=None, environment={}, issues=())
    values.update(updates)
    return Snapshot(**values)


def test_missing_root_and_opaque_coordinate_stay_unknown():
    snap = make_snapshot()
    assert snap.root_id is None
    assert snap.components[0].coordinate is None
    assert snap.components[0].dependencies_known is False
    assert Snapshot.model_validate_json(snap.model_dump_json()) == snap


def test_distinct_instances_may_share_global_coordinate():
    coordinate = identify("requests", "2.32.3", None)
    a = Component(local_id="a", name="requests", coordinate=coordinate,
                  dependencies_known=True, pointer="/a")
    b = a.model_copy(update={"local_id": "b", "pointer": "/b"})
    assert len(make_snapshot(components=(a,b)).components) == 2


def test_duplicate_instances_dangling_edges_and_unknown_root_are_rejected():
    component = make_snapshot().components[0]
    with pytest.raises(ValidationError, match="DUPLICATE_COMPONENT"):
        make_snapshot(components=(component,component))
    with pytest.raises(ValidationError, match="DANGLING_EDGE"):
        make_snapshot(edges=(Edge(from_id="r", to_id="missing", requirement=None, pointer="/edges/0"),))
    with pytest.raises(ValidationError, match="UNKNOWN_ROOT"):
        make_snapshot(root_id="missing")


def test_models_reject_coercion_and_unknown_fields():
    with pytest.raises(ValidationError):
        Component(local_id=12, name="root", coordinate=None, dependencies_known=False, pointer="/root")
    with pytest.raises(ValidationError):
        make_snapshot(safe=True)
    with pytest.raises(ValidationError):
        make_snapshot(components=list(make_snapshot().components))
