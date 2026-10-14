import hashlib
import itertools
import json
from pathlib import Path

import networkx as nx

from depscope.ingest.models import Contract
from depscope.investigation.models import InvestigationScope
from depscope.runtime.config import PROJECT_ROOT
from depscope.runtime.errors import DomainError

from .reference import RawReference, name

QUOTAS = {
    "single": (12, 28),
    "path": (18, 42),
    "cross": (12, 28),
    "comparison": (12, 28),
    "missing": (6, 14),
}


class Question(Contract):
    id: str
    kind: str
    split: str
    family_names: tuple[str, ...]
    scope: InvestigationScope
    prompt: str
    source_ids: tuple[str, ...]
    expected_facts: tuple[dict, ...]
    required_evidence: tuple[str, ...] = ()
    reference_locators: tuple[dict, ...]
    label_origin: str = "program_reference"
    review_status: str = "not_human_reviewed"


def family_split(family_name, all_families):
    ordered = sorted(
        all_families, key=lambda n: hashlib.sha256(("20261013:" + n).encode()).hexdigest()
    )
    return "dev" if family_name in ordered[:3] else "test"


def build_benchmark(manifest, home=None):
    home = Path(home or PROJECT_ROOT / "artifacts/corpus")
    reference = RawReference(home)
    families = tuple(sorted({c.family_name for c in manifest.cases}))
    candidates = {fold: {kind: [] for kind in QUOTAS} for fold in ("dev", "test")}
    cases = tuple(
        sorted(
            (c for c in manifest.cases if c.completeness == "complete"),
            key=lambda c: (c.family_name, c.package, c.version),
        )
    )
    by_id = {c.snapshot_id: c for c in cases}

    def add(kind, selected, prompt, facts, locators, comparison_id=None):
        fold = family_split(selected[0].family_name, families)
        if any(family_split(c.family_name, families) != fold for c in selected):
            return
        scope = InvestigationScope(
            project_ids=tuple(sorted({c.project_id for c in selected})),
            snapshot_ids=tuple(c.snapshot_id for c in selected),
            run_map={c.snapshot_id: c.run_id for c in selected},
            comparison_id=comparison_id,
        )
        payload = {
            "kind": kind,
            "scope": scope.model_dump(mode="json"),
            "prompt": prompt,
            "expected_facts": facts,
            "reference_locators": locators,
        }
        id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        candidates[fold][kind].append(
            Question(
                id=id,
                kind=kind,
                split=fold,
                family_names=tuple(sorted({c.family_name for c in selected})),
                scope=scope,
                prompt=prompt,
                source_ids=tuple(
                    sorted(
                        {c.source_digest for c in selected}
                        | {
                            source
                            for locator in locators
                            for source in locator.get("upstream_source_ids", [])
                        }
                        | (set(reference.comparison_sources(selected)) if comparison_id else set())
                    )
                ),
                expected_facts=tuple(facts),
                reference_locators=tuple(locators),
            )
        )

    for case in cases:
        doc, graph = reference.graph(case)
        counts = {
            name(n["versionKey"]["name"]): sum(
                name(other["versionKey"]["name"]) == name(n["versionKey"]["name"])
                for other in doc["nodes"]
            )
            for n in doc["nodes"]
        }
        for index, node in enumerate(doc["nodes"]):
            package = name(node["versionKey"]["name"])
            if counts[package] != 1:
                continue
            add(
                "single",
                (case,),
                f"In the selected {case.package} {case.version} public resolution, what exact version is recorded for {package}? Return its version fact.",
                [reference.version(case, index)],
                [{"source_digest": case.source_digest, "pointer": f"/nodes/{index}"}],
            )
            query = reference.query_fact(case, index)
            if query:
                fact, locator = query
                add(
                    "single",
                    (case,),
                    f"In the selected {case.package} {case.version} public case, what status did the frozen OSV query return for {package} at its recorded version? Give the query status fact; a query status does not establish exploitability or safety.",
                    [fact],
                    [locator],
                )
            if index and nx.has_path(graph, 0, index):
                distance = nx.shortest_path_length(graph, 0, index)
                if (
                    2 <= distance <= 4
                    and sum(1 for _ in itertools.islice(nx.all_shortest_paths(graph, 0, index), 2))
                    == 1
                ):
                    fact, locators = reference.path(case, index)
                    add(
                        "path",
                        (case,),
                        f"In the selected {case.package} {case.version} graph, give one shortest recorded dependency path from the root {case.package} to {package}.",
                        [fact],
                        locators,
                    )
        add(
            "missing",
            (case,),
            f"Did the {case.package} {case.version} application successfully install and pass integration tests on its deployed environment? Give verifiable evidence for that conclusion.",
            [],
            [
                {
                    "source_digest": case.source_digest,
                    "pointer": "/nodes/0",
                    "missing": "actual_installed_environment_and_test_receipt",
                }
            ],
        )

    for left, right in itertools.combinations(cases, 2):
        if left.project_id == right.project_id or family_split(
            left.family_name, families
        ) != family_split(right.family_name, families):
            continue
        dl, gl = reference.graph(left)
        dr, gr = reference.graph(right)

        def reachable(doc, graph):
            result = {}
            for i, n in enumerate(doc["nodes"]):
                if (
                    i
                    and nx.has_path(graph, 0, i)
                    and 1 <= nx.shortest_path_length(graph, 0, i) <= 3
                ):
                    key = name(n["versionKey"]["name"])
                    result.setdefault(key, []).append(i)
            return {
                key: values[0]
                for key, values in result.items()
                if len(values) == 1
                and sum(1 for _ in itertools.islice(nx.all_shortest_paths(graph, 0, values[0]), 2))
                == 1
            }

        a, b = reachable(dl, gl), reachable(dr, gr)
        for package in sorted(a.keys() & b.keys()):
            f1, l1 = reference.path(left, a[package])
            f2, l2 = reference.path(right, b[package])
            add(
                "cross",
                (left, right),
                f"Investigate potential dependency impact of {package} across the two selected public cases, {left.package} {left.version} and {right.package} {right.version}. Return one shortest recorded root-to-{package} path separately for each snapshot; this does not establish exploitability.",
                [f1, f2],
                l1 + l2,
            )

    for id in manifest.comparison_ids:
        comparison = json.loads((home / "comparisons" / (id + ".json")).read_bytes())
        left, right = by_id[comparison["baseline_id"]], by_id[comparison["candidate_id"]]
        values = reference.comparison(left, right, id)
        if any(values[k] != comparison[k] for k in values):
            raise DomainError(
                "REFERENCE_DISAGREEMENT",
                "Independent raw-query comparison disagrees; retain this as a defect, never copy the product label",
            )
        for metric, value in values.items():
            add(
                "comparison",
                (left, right),
                f"For the selected comparison from {left.package} {left.version} to {right.version}, return exactly the recorded {metric} comparison metric. Treat advisory changes as known matches, not proof of security or compatibility.",
                [
                    {
                        "kind": "comparison",
                        "value": {"comparison_id": id, "metric": metric, "value": value},
                    }
                ],
                [
                    {
                        "comparison_id": id,
                        "metric": metric,
                        "source_digests": [left.source_digest, right.source_digest],
                    }
                ],
                id,
            )

    selected = []
    seen = set()
    for split, quota_index in (("dev", 0), ("test", 1)):
        for kind, quotas in QUOTAS.items():
            rows = sorted(
                candidates[split][kind],
                key=lambda q: hashlib.sha256(("20261013:" + q.id).encode()).hexdigest(),
            )
            # Round-robin actual family groups so the large LangChain family cannot consume all questions.
            groups = {}
            for q in rows:
                groups.setdefault(q.family_names, []).append(q)
            ordered = []
            while any(groups.values()):
                for group in sorted(groups):
                    if groups[group]:
                        ordered.append(groups[group].pop(0))
            accepted = []
            for q in ordered:
                key = json.dumps([q.reference_locators, q.expected_facts], sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    accepted.append(q)
                if len(accepted) == quotas[quota_index]:
                    break
            if len(accepted) != quotas[quota_index]:
                raise DomainError(
                    "BENCHMARK_COVERAGE_GAP", f"Insufficient real cases for {split}/{kind}"
                )
            selected.extend(accepted)
    return tuple(selected)
