import json
import random
from collections import defaultdict


def evidence_recall(required, retrieved):
    return len(required & retrieved) / len(required) if required else None


def score_answer(question, answer):
    gold = question["expected_facts"]
    actual = [{"kind": f.kind, "value": f.value} for f in answer.facts]

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    correct = answer.status == "answered" and sorted(map(canonical, actual)) == sorted(
        map(canonical, gold)
    )
    abstention = question["kind"] == "missing" and answer.status == "insufficient_evidence"
    return {
        "exact_fact_accuracy": correct if question["kind"] != "missing" else None,
        "correct_abstention": abstention if question["kind"] == "missing" else None,
        "evidence_recall_at_10": evidence_recall(
            set(question["required_evidence"]), set(answer.supplied_evidence_ids)
        ),
        "citation_locatable": len(set(answer.citations) & set(answer.supplied_evidence_ids))
        / len(set(answer.citations))
        if answer.citations
        else None,
        "citation_semantic_support": None,
        "service_failure": answer.status
        in ("generation_error", "retrieval_error", "budget_exhausted"),
        "parse_failure": answer.status == "parse_error",
        "unsupported_output": answer.status == "unsupported_output",
        "status": answer.status,
    }


def cluster_interval(rows, seed=20261013, replicates=1000):
    groups = defaultdict(list)
    for row in rows:
        if row["delta"] is not None:
            groups[row["cluster"]].append(row["delta"])
    names = sorted(groups)
    rng = random.Random(seed)
    if not names:
        return {
            "groups": 0,
            "replicates": replicates,
            "lower": None,
            "upper": None,
            "unstable": True,
        }
    samples = []
    for _ in range(replicates):
        values = [value for group in rng.choices(names, k=len(names)) for value in groups[group]]
        samples.append(sum(values) / len(values))
    samples.sort()
    return {
        "groups": len(names),
        "replicates": replicates,
        "lower": samples[int(replicates * 0.025)],
        "upper": samples[min(replicates - 1, int(replicates * 0.975))],
        "unstable": len(names) < 10,
        "interpretation": "Descriptive family/composite-family stability only; overlapping cross-project families are not independent population samples.",
    }
