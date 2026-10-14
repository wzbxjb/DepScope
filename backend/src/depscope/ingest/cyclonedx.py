import hashlib
import json

from depscope.identity.coordinates import identify, snapshot_key
from depscope.ingest.models import Component, Edge, Snapshot, SourceRef
from depscope.runtime.errors import DomainError

from .limits import MAX_COMPONENTS, MAX_EDGES, read_limited
from .schemas import cyclonedx_validator


def _pointer(parts) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise DomainError("INVALID_JSON", "Duplicate object keys are not accepted")
        obj[key] = value
    return obj


def parse_cyclonedx(raw: bytes, project_id: str, source: SourceRef, environment: dict) -> Snapshot:
    raw = read_limited((raw,))
    if hashlib.sha256(raw).hexdigest() != source.digest:
        raise DomainError("SOURCE_DIGEST_MISMATCH", "Raw record does not match source digest")
    try:
        doc = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise DomainError("INVALID_JSON", "Upload must be finite, valid JSON") from None
    if (
        not isinstance(doc, dict)
        or doc.get("bomFormat") != "CycloneDX"
        or doc.get("specVersion") != "1.6"
    ):
        raise DomainError(
            "UNSUPPORTED_FORMAT", "Only CycloneDX 1.6 JSON is supported", ("/specVersion",)
        )
    # Bound counts before expensive schema checks. Walk iteratively to avoid recursive graph parsing.
    components = []
    stack = (
        [
            (row, f"/components/{i}")
            for i, row in reversed(list(enumerate(doc.get("components", []))))
        ]
        if isinstance(doc.get("components", []), list)
        else []
    )
    metadata = doc.get("metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get("component"), dict):
        stack.append((metadata["component"], "/metadata/component"))
    while stack:
        row, pointer = stack.pop()
        components.append((row, pointer))
        if len(components) > MAX_COMPONENTS:
            raise DomainError("LIMIT_EXCEEDED", "More than 10,000 components", (pointer,))
        if isinstance(row, dict) and isinstance(row.get("components"), list):
            stack.extend(
                (child, f"{pointer}/components/{i}")
                for i, child in reversed(list(enumerate(row["components"])))
            )
    dependency_rows = doc.get("dependencies", [])
    if isinstance(dependency_rows, list):
        edge_count = sum(
            len(row.get("dependsOn", []))
            for row in dependency_rows
            if isinstance(row, dict) and isinstance(row.get("dependsOn", []), list)
        )
        if edge_count > MAX_EDGES:
            raise DomainError(
                "LIMIT_EXCEEDED", "More than 50,000 dependency edges", ("/dependencies",)
            )
    try:
        error = next(cyclonedx_validator().iter_errors(doc), None)
    except RecursionError:
        raise DomainError("INVALID_JSON", "Document nesting exceeds validator capacity") from None
    if error:
        raise DomainError(
            "INVALID_BOM",
            "Document does not conform to CycloneDX 1.6",
            (_pointer(error.absolute_path),),
        )
    entries = {}
    for row, pointer in components:
        local_id = (
            row.get("bom-ref") or "unreferenced:" + hashlib.sha256(pointer.encode()).hexdigest()
        )
        if local_id in entries:
            raise DomainError(
                "DUPLICATE_COMPONENT",
                "Repeated component reference",
                (entries[local_id][1] + "/bom-ref", pointer + "/bom-ref"),
            )
        entries[local_id] = (row, pointer)
    known = set()
    seen_records = set()
    edges = []
    for i, row in enumerate(dependency_rows):
        pointer = f"/dependencies/{i}"
        origin = row["ref"]
        if origin not in entries:
            raise DomainError(
                "DANGLING_EDGE", "Dependency origin is not a component", (pointer + "/ref",)
            )
        if origin in seen_records:
            raise DomainError(
                "DUPLICATE_DEPENDENCY_RECORD",
                "Repeated dependency declaration",
                (pointer + "/ref",),
            )
        seen_records.add(origin)
        if "dependsOn" in row:
            known.add(origin)
        for j, target in enumerate(row.get("dependsOn", [])):
            edge_pointer = f"{pointer}/dependsOn/{j}"
            if target not in entries:
                raise DomainError(
                    "DANGLING_EDGE", "Dependency target is not a component", (edge_pointer,)
                )
            edges.append(Edge(from_id=origin, to_id=target, pointer=edge_pointer))
    parsed = []
    issues = []
    root_id = None
    for local_id, (row, pointer) in entries.items():
        try:
            coordinate = identify(row["name"], row.get("version"), row.get("purl"))
        except DomainError as exc:
            raise DomainError(exc.code, exc.message, (pointer + "/purl",)) from None
        private_root = (
            pointer == "/metadata/component"
            and row.get("type") == "application"
            and any(
                p.get("name") == "depscope:identity-scope"
                and p.get("value") == "private-application"
                for p in row.get("properties", [])
            )
        )
        if private_root:
            if row.get("purl"):
                raise DomainError(
                    "PRIVATE_IDENTITY_CONFLICT",
                    "A private application root cannot declare a public package URL",
                    (pointer + "/purl",),
                )
            coordinate = None
            environment = {**environment, "private_application_root": True}
        parsed.append(
            Component(
                local_id=local_id,
                name=row["name"],
                coordinate=coordinate,
                dependencies_known=local_id in known,
                pointer=pointer,
            )
        )
        if local_id not in known:
            issues.append("unknown_dependencies:" + local_id)
        if coordinate is None:
            issues.append("opaque_coordinate:" + local_id)
        if pointer == "/metadata/component":
            root_id = local_id
    if root_id is None:
        issues.append("missing_root")
    return Snapshot(
        snapshot_id=snapshot_key(project_id, "observed_environment", source.digest),
        project_id=project_id,
        source_kind="observed_environment",
        source=source,
        components=tuple(parsed),
        edges=tuple(edges),
        root_id=root_id,
        environment=environment,
        issues=tuple(issues),
    )
