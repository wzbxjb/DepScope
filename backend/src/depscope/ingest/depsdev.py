import hashlib
import json

from depscope.identity.coordinates import identify, snapshot_key
from depscope.ingest.models import Component, Edge, Snapshot, SourceRef
from depscope.runtime.errors import DomainError

from .limits import MAX_COMPONENTS, MAX_EDGES, read_limited


def parse_depsdev(raw: bytes, project_id: str, source: SourceRef) -> Snapshot:
    raw = read_limited((raw,))
    if hashlib.sha256(raw).hexdigest() != source.digest:
        raise DomainError("SOURCE_DIGEST_MISMATCH", "Raw record does not match source digest")
    try:
        doc = json.loads(raw)
        nodes, rows = doc["nodes"], doc["edges"]
        if not isinstance(nodes, list) or not isinstance(rows, list):
            raise TypeError
    except (ValueError, TypeError, KeyError):
        raise DomainError("INVALID_PUBLIC_GRAPH", "deps.dev graph structure is invalid") from None
    if len(nodes) > MAX_COMPONENTS or len(rows) > MAX_EDGES:
        raise DomainError("LIMIT_EXCEEDED", "Public graph exceeds component or edge limit")
    issues = []
    graph_error = doc.get("error")
    if graph_error:
        issues.append("resolution_error:" + str(graph_error))
    components = []
    for i, node in enumerate(nodes):
        try:
            key = node["versionKey"]
            name = key["name"]
            coordinate = identify(name, key.get("version"), None) if key["system"] == "PYPI" else None
            errors = node.get("errors", [])
            for error in errors:
                issues.append(f"node_error:{i}:" + json.dumps(error, sort_keys=True))
            components.append(Component(local_id=str(i), name=name, coordinate=coordinate,
                              dependencies_known=not bool(errors or graph_error), pointer=f"/nodes/{i}"))
            if coordinate is None:
                issues.append(f"opaque_coordinate:{i}")
        except (KeyError, TypeError, ValueError):
            raise DomainError("INVALID_PUBLIC_GRAPH", "Invalid deps.dev node", (f"/nodes/{i}",)) from None
    edges = []
    for i, edge in enumerate(rows):
        origin, target = edge.get("fromNode"), edge.get("toNode")
        if type(origin) is not int or type(target) is not int or not (0 <= origin < len(nodes) and 0 <= target < len(nodes)):
            raise DomainError("DANGLING_EDGE", "Invalid deps.dev node index", (f"/edges/{i}",))
        edges.append(Edge(from_id=str(origin), to_id=str(target), requirement=edge.get("requirement"), pointer=f"/edges/{i}"))
    root = "0" if nodes and nodes[0].get("relation") == "SELF" else None
    if root is None:
        issues.append("missing_root")
    return Snapshot(snapshot_id=snapshot_key(project_id,"public_resolution",source.digest),
                    project_id=project_id, source_kind="public_resolution", source=source,
                    components=tuple(components), edges=tuple(edges), root_id=root,
                    environment={"resolution_context":"deps.dev generic Linux",
                                 "historical_environment":False}, issues=tuple(issues))
