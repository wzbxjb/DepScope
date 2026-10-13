from collections import defaultdict, deque

from depscope.ingest.models import Snapshot


def breadth_first(snapshot: Snapshot, start: str | None = None, reverse: bool = False) -> dict[str,str | None]:
    start=snapshot.root_id if start is None else start
    if start is None or start not in {c.local_id for c in snapshot.components}:
        return {}
    adjacency=defaultdict(set)
    for edge in snapshot.edges:
        origin,target=(edge.to_id,edge.from_id) if reverse else (edge.from_id,edge.to_id)
        adjacency[origin].add(target)
    parents={start:None}
    queue=deque([start])
    while queue:
        node=queue.popleft()
        for other in sorted(adjacency[node]):
            if other not in parents:
                parents[other]=node
                queue.append(other)
    return parents


def reconstruct(parents: dict[str,str | None], target: str) -> tuple[str,...] | None:
    if target not in parents:
        return None
    path=[]
    node=target
    while node is not None:
        path.append(node)
        node=parents[node]
    return tuple(reversed(path))


def shortest_path(snapshot: Snapshot, target_id: str) -> tuple[str,...] | None:
    return reconstruct(breadth_first(snapshot),target_id)
