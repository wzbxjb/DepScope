"""Controlled observed-environment normalization; uploaded graphs never receive this proof."""

import copy
from pathlib import Path
from urllib.parse import unquote, urlsplit

from packaging.requirements import Requirement
from packaging.version import Version

from depscope.identity.coordinates import normalized_name
from depscope.runtime.errors import DomainError


def normalize_owned_sbom(doc, inspected, project_dir):
    normalized = copy.deepcopy(doc)
    root = normalized["metadata"]["component"]
    name, version = normalized_name(root["name"]), Version(root["version"])
    owned = [r for r in inspected["installed"] if normalized_name(r["metadata"]["name"]) == name]
    if len(owned) != 1 or Version(owned[0]["metadata"]["version"]) != version:
        raise DomainError("OWNERSHIP_UNPROVEN", "Installed application identity is not proven")
    url = urlsplit(owned[0].get("direct_url", {}).get("url", ""))
    if (
        url.scheme != "file"
        or url.netloc
        or Path(unquote(url.path)).resolve() != Path(project_dir).resolve()
    ):
        raise DomainError(
            "OWNERSHIP_UNPROVEN", "Application distribution belongs to another source"
        )
    candidates = [
        c
        for c in normalized.get("components", [])
        if normalized_name(c["name"]) == name and Version(c["version"]) == version
    ]
    if len(candidates) > 1:
        raise DomainError(
            "OWNERSHIP_AMBIGUOUS", "Multiple application distributions cannot be merged"
        )
    duplicate = candidates[0]["bom-ref"] if candidates else None
    root_id = root["bom-ref"]
    normalized["components"] = [
        c for c in normalized.get("components", []) if c.get("bom-ref") != duplicate
    ]
    root.pop("purl", None)
    root["properties"] = [
        p for p in root.get("properties", []) if p["name"] != "depscope:identity-scope"
    ] + [{"name": "depscope:identity-scope", "value": "private-application"}]
    rows = {}
    for row in normalized.get("dependencies", []):
        origin = root_id if row["ref"] == duplicate else row["ref"]
        rows.setdefault(origin, set()).update(
            root_id if target == duplicate else target for target in row.get("dependsOn", [])
        )
    if duplicate:
        rows[root_id].discard(root_id)
    normalized["dependencies"] = [
        {"ref": ref, "dependsOn": sorted(targets)} for ref, targets in sorted(rows.items())
    ]
    return normalized, {"merged_distribution_ref": duplicate, "application_source_proven": True}


def reconcile_installed_dependencies(doc, inspected, environment):
    """Derive edges independently from installed Requires-Dist, evaluating proven extras/markers.

    The original tool output and every correction are retained by the runner. Absence of a
    dependency entry is not treated as an empty dependency list until metadata proves it.
    """
    result = copy.deepcopy(doc)
    root = result["metadata"]["component"]
    components = result.get("components", []) + [root]
    installed = {
        normalized_name(r["metadata"]["name"]): r["metadata"] for r in inspected["installed"]
    }
    refs = {}
    for component in components:
        name = normalized_name(component["name"])
        if (
            name in refs
            or name not in installed
            or Version(component["version"]) != Version(installed[name]["version"])
        ):
            raise DomainError(
                "INVENTORY_MISMATCH", "Installed inventory and SBOM identities differ"
            )
        refs[name] = component["bom-ref"]
    if set(refs) != set(installed):
        raise DomainError("INVENTORY_MISMATCH", "SBOM omits installed distributions")
    selected = {name: set() for name in installed}
    selected[normalized_name(root["name"])].update(environment["extras"])
    active = {}
    changed = True
    while changed:
        changed = False
        for name, metadata in installed.items():
            for expression in metadata.get("requires_dist", []):
                requirement = Requirement(expression)
                if requirement.marker and not any(
                    requirement.marker.evaluate(
                        {**environment["marker_environment"], "extra": extra}
                    )
                    for extra in ("", *sorted(selected[name]))
                ):
                    continue
                target = normalized_name(requirement.name)
                if (
                    requirement.url
                    or target not in installed
                    or not requirement.specifier.contains(
                        installed[target]["version"], prereleases=True
                    )
                ):
                    raise DomainError(
                        "INSTALLED_CONSTRAINT_FAILURE",
                        "An active dependency is absent or does not meet its declaration",
                    )
                previous = len(selected[target])
                selected[target].update(requirement.extras)
                changed |= len(selected[target]) != previous
                active[(name, target)] = expression
    declarations = []
    expected = {ref: set() for ref in refs.values()}
    for (origin, target), expression in sorted(active.items()):
        requirement = Requirement(expression)
        expected[refs[origin]].add(refs[target])
        declarations.append(
            {
                "from_id": refs[origin],
                "to_id": refs[target],
                "requirement": requirement.name + str(requirement.specifier),
                "original_requirement": expression,
                "selected_origin_extras": sorted(selected[origin]),
            }
        )
    original = {
        (r["ref"], target)
        for r in result.get("dependencies", [])
        for target in r.get("dependsOn", [])
    }
    edges = {(origin, target) for origin, targets in expected.items() for target in targets}
    result["dependencies"] = [
        {"ref": origin, "dependsOn": sorted(targets)}
        for origin, targets in sorted(expected.items())
    ]
    audit = {
        "tool_missing_edges": [list(e) for e in sorted(edges - original)],
        "tool_extra_edges": [list(e) for e in sorted(original - edges)],
        "selected_extras": {name: sorted(extras) for name, extras in sorted(selected.items())},
        "independently_checked_nodes": len(components),
        "independently_checked_edges": len(edges),
    }
    return result, declarations, audit
