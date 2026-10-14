from depscope.runtime.errors import DomainError
from depscope.investigation.models import InvestigationScope
import pytest


def test_comparison_scope_requires_the_comparison_run_map(snapshot_factory):
    from types import SimpleNamespace
    from depscope.investigation.models import validate_scope

    a = snapshot_factory("p", ("a",), (), "a")
    b = snapshot_factory("p", ("b",), (), "b")
    snapshots = {s.snapshot_id: s for s in (a, b)}
    scope = InvestigationScope(
        project_ids=("p",),
        snapshot_ids=(a.snapshot_id, b.snapshot_id),
        run_map={a.snapshot_id: "old-a", b.snapshot_id: "old-b"},
        comparison_id="comparison",
    )
    comparison = SimpleNamespace(
        baseline_id=a.snapshot_id, candidate_id=b.snapshot_id, run_ids=("selected-a", "selected-b")
    )
    with pytest.raises(DomainError):
        validate_scope(
            scope,
            SimpleNamespace(load=lambda id: snapshots[id]),
            SimpleNamespace(
                load=lambda id: SimpleNamespace(
                    snapshot_id=a.snapshot_id if id == "old-a" else b.snapshot_id
                )
            ),
            SimpleNamespace(load=lambda id: comparison),
        )
