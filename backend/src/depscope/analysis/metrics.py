from typing import Literal

from depscope.ingest.models import Contract, Snapshot

from .paths import breadth_first


class Completeness(Contract):
    state: Literal["complete","partial","unknown"]
    root_known: bool
    unknown_dependencies: int
    issues: tuple[str,...]


def completeness(snapshot: Snapshot) -> Completeness:
    unknown=sum(not c.dependencies_known for c in snapshot.components)
    resolution_error=any(i.startswith(("resolution_error:","node_error:")) for i in snapshot.issues)
    state="unknown" if snapshot.root_id is None else ("partial" if unknown or resolution_error else "complete")
    return Completeness(state=state,root_known=snapshot.root_id is not None,
                        unknown_dependencies=unknown,issues=snapshot.issues)


def graph_metrics(snapshot: Snapshot) -> dict:
    parents=breadth_first(snapshot)
    return {"total_nodes":len(snapshot.components),"total_edges":len(snapshot.edges),
            "root_reachable":len(parents) if snapshot.root_id is not None else None,
            "unreachable":len(snapshot.components)-len(parents) if snapshot.root_id is not None else None,
            "completeness":completeness(snapshot).model_dump(mode="json")}


def reverse_impact(snapshot: Snapshot, local_id: str) -> tuple[str,...]:
    return tuple(breadth_first(snapshot,local_id,reverse=True))
