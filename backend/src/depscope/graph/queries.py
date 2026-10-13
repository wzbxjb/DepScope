import hashlib
from collections import defaultdict, deque

from depscope.analysis.matching import query_key
from depscope.analysis.metrics import Completeness, completeness
from depscope.analysis.paths import breadth_first
from depscope.identity.coordinates import instance_key
from depscope.ingest.models import Contract, Coordinate
from depscope.runtime.errors import DomainError


class GraphNode(Contract):
    id: str
    local_id: str
    label: str
    coordinate: Coordinate | None
    query_status: str
    pointer: str


class GraphEdge(Contract):
    id: str
    source: str
    target: str
    requirement: str | None
    pointer: str


class GraphView(Contract):
    snapshot_id: str
    nodes: tuple[GraphNode,...]
    edges: tuple[GraphEdge,...]
    total_nodes: int
    hidden_nodes: int
    completeness: Completeness
    run_id: str | None
    observed_at: str
    query_observed_at: str | None


class GraphService:
    def __init__(self,snapshots,runs):
        self.snapshots,self.runs=snapshots,runs

    def view(self,snapshot_id: str,focus_id: str | None = None,run_id: str | None = None) -> GraphView:
        snapshot=self.snapshots.load(snapshot_id)
        run=None
        if run_id:
            run=self.runs.load(run_id)
            if run.snapshot_id != snapshot_id:
                raise DomainError("SCOPE_MISMATCH", "Match run belongs to a different snapshot")
        else:
            try:
                run=self.runs.latest(snapshot_id)
            except DomainError as exc:
                if exc.code != "MATCH_RUN_NOT_FOUND":
                    raise
        statuses={query_key(q.coordinate):q.status for q in run.queries} if run else {}
        keys={instance_key(snapshot_id,c.local_id):c.local_id for c in snapshot.components}
        if focus_id is not None:
            focus=keys.get(focus_id)
            if focus is None:
                raise DomainError("SCOPE_MISMATCH", "Graph focus is outside this snapshot")
            adjacency=defaultdict(set)
            for edge in snapshot.edges:
                adjacency[edge.from_id].add(edge.to_id)
                adjacency[edge.to_id].add(edge.from_id)
            order=[focus]
            seen={focus}
            queue=deque([focus])
            while queue and len(order)<200:
                for other in sorted(adjacency[queue.popleft()]):
                    if other not in seen:
                        seen.add(other)
                        order.append(other)
                        queue.append(other)
                        if len(order)==200:
                            break
        else:
            order=list(breadth_first(snapshot))
            reached=set(order)
            order.extend(sorted(c.local_id for c in snapshot.components if c.local_id not in reached))
        shown=set(order[:200])
        nodes=tuple(GraphNode(id=instance_key(snapshot_id,c.local_id),local_id=c.local_id,
                    label=c.name+('@'+c.coordinate.raw_version if c.coordinate else ''),
                    coordinate=c.coordinate,query_status=statuses.get(query_key(c.coordinate),"unqueried") if c.coordinate else "unqueried",pointer=c.pointer)
                    for c in snapshot.components if c.local_id in shown)
        edges=tuple(GraphEdge(id=hashlib.sha256((snapshot_id+":"+e.pointer).encode()).hexdigest(),
                    source=instance_key(snapshot_id,e.from_id),target=instance_key(snapshot_id,e.to_id),
                    requirement=e.requirement,pointer=e.pointer)
                    for e in snapshot.edges if e.from_id in shown and e.to_id in shown)
        return GraphView(snapshot_id=snapshot_id,nodes=nodes,edges=edges,total_nodes=len(snapshot.components),
                    hidden_nodes=len(snapshot.components)-len(nodes),completeness=completeness(snapshot),
                    run_id=run.id if run else None,observed_at=snapshot.source.observed_at,
                    query_observed_at=run.observed_at if run else None)
