from pydantic import model_validator

from depscope.ingest.models import Contract


class InvestigationScope(Contract):
    project_ids: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    run_map: dict[str, str]
    comparison_id: str | None = None

    @model_validator(mode="after")
    def explicit_scope(self):
        if not self.project_ids or not self.snapshot_ids:
            raise ValueError("Explicit project and snapshot selection is required")
        if len(set(self.snapshot_ids)) != len(self.snapshot_ids) or set(self.run_map) != set(
            self.snapshot_ids
        ):
            raise ValueError("Exactly one explicit match run is required per selected snapshot")
        if len(self.snapshot_ids) > 50:
            raise ValueError("At most 50 snapshots per investigation")
        return self


def validate_scope(scope, snapshots, runs, comparisons=None):
    from depscope.runtime.errors import DomainError

    selected = tuple(snapshots.load(sid) for sid in scope.snapshot_ids)
    if {s.project_id for s in selected} != set(scope.project_ids):
        raise DomainError(
            "SCOPE_MISMATCH",
            "Every selected snapshot must belong to the explicit project selection",
        )
    for snapshot in selected:
        if runs.load(scope.run_map[snapshot.snapshot_id]).snapshot_id != snapshot.snapshot_id:
            raise DomainError("SCOPE_MISMATCH", "Match run belongs to another snapshot")
    if scope.comparison_id:
        if comparisons is None:
            raise DomainError("SCOPE_MISMATCH", "Comparison selection cannot be validated")
        comparison = comparisons.load(scope.comparison_id)
        if not {comparison.baseline_id, comparison.candidate_id} <= set(scope.snapshot_ids):
            raise DomainError("SCOPE_MISMATCH", "Comparison snapshots must both be selected")
    return selected
