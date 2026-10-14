from depscope.investigation.models import validate_scope
from depscope.runtime.errors import DomainError

from .answers import ToolFact


class ReadOnlyTools:
    def __init__(self, snapshots, runs, paths, comparisons):
        self.snapshots, self.runs, self.paths, self.comparisons = (
            snapshots,
            runs,
            paths,
            comparisons,
        )

    def execute(self, operation, args, scope):
        if operation not in {"path", "count", "advisory", "comparison"}:
            raise DomainError(
                "TOOL_NOT_ALLOWED", "Only predefined read-only investigation tools are allowed"
            )
        snapshots = validate_scope(scope, self.snapshots, self.runs, self.comparisons)
        if operation == "count":
            if set(args) != {"snapshot_id"} or args["snapshot_id"] not in scope.snapshot_ids:
                raise DomainError("SCOPE_MISMATCH", "Choose a selected snapshot")
            snapshot = next(s for s in snapshots if s.snapshot_id == args["snapshot_id"])
            run = self.runs.load(scope.run_map[snapshot.snapshot_id])
            return ToolFact(
                kind="count",
                value={
                    "snapshot_id": snapshot.snapshot_id,
                    "instances": len(snapshot.components),
                    "recorded_edges": len(snapshot.edges),
                    "query_coverage": run.coverage,
                },
                source_ids=(snapshot.source.digest,),
            )
        if operation == "path":
            if set(args) != {"finding_id"}:
                raise DomainError("TOOL_ARGUMENTS", "Only finding_id is allowed")
            finding, run = self.runs.finding(args["finding_id"])
            if scope.run_map.get(run.snapshot_id) != run.id:
                raise DomainError("SCOPE_MISMATCH", "Finding belongs to another selected run")
            result = self.paths.paths(finding.id, scope.run_map)
            return ToolFact(
                kind="path",
                value=result.model_dump(mode="json"),
                source_ids=tuple(s.source.digest for s in snapshots),
            )
        if operation == "advisory":
            if set(args) != {"revision_id"}:
                raise DomainError("TOOL_ARGUMENTS", "Only revision_id is allowed")
            allowed = {
                rid for run in scope.run_map.values() for rid in self.runs.load(run).revision_ids
            }
            if args["revision_id"] not in allowed:
                raise DomainError("SCOPE_MISMATCH", "Advisory revision is outside selected runs")
            revision = self.runs.revision(args["revision_id"])
            return ToolFact(
                kind="advisory",
                value=revision.model_dump(mode="json"),
                source_ids=(revision.digest,),
            )
        if set(args) != {"comparison_id"} or args["comparison_id"] != scope.comparison_id:
            raise DomainError("SCOPE_MISMATCH", "Choose the explicit scoped comparison")
        result = self.comparisons.load(args["comparison_id"])
        return ToolFact(
            kind="comparison",
            value=result.model_dump(mode="json"),
            source_ids=tuple(s.source.digest for s in snapshots),
        )
