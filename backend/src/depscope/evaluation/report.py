import statistics
from collections import defaultdict

from depscope.evaluation.metrics import cluster_interval


def mean(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def summarize(rows):
    latency = sorted(r["latency_seconds"] for r in rows)
    return {
        "questions": len(rows),
        "evidence_recall_at_10": mean(r["scores"]["evidence_recall_at_10"] for r in rows),
        "exact_fact_accuracy": mean(r["scores"]["exact_fact_accuracy"] for r in rows),
        "correct_abstention": mean(r["scores"]["correct_abstention"] for r in rows),
        "citation_locatable": mean(r["scores"]["citation_locatable"] for r in rows),
        "citation_semantic_support": None,
        "service_failure_rate": mean(r["scores"]["service_failure"] for r in rows),
        "parse_failure_rate": mean(r["scores"]["parse_failure"] for r in rows),
        "unsupported_output_rate": mean(r["scores"]["unsupported_output"] for r in rows),
        "latency_median_seconds": statistics.median(latency) if latency else None,
        "latency_p95_seconds": latency[min(len(latency) - 1, int(len(latency) * 0.95))]
        if latency
        else None,
        "status_counts": {
            status: sum(r["answer"]["status"] == status for r in rows)
            for status in sorted({r["answer"]["status"] for r in rows})
        },
    }


def make_report(rows, config):
    methods = defaultdict(list)
    by_question = defaultdict(dict)
    for row in rows:
        methods[row["method"]].append(row)
        by_question[row["question_id"]][row["method"]] = row
    report = {
        "methods": {},
        "paired_deltas": [],
        "family_intervals": {},
        "limitations": [
            "Program reference labels; no human semantic audit. Citation location is not semantic support.",
            "Exact facts are scored on all non-missing questions, including refusals and failures. Missing questions have a separate abstention denominator.",
            "Families share downstream packages/advisories across splits. Composite-family cross-project groups overlap; intervals are descriptive and may be unstable.",
            "Cases are current public dependency resolutions, not enterprise deployments or historical installed environments.",
            "Latency includes query embedding, scoped retrieval, remote generation and validation at concurrency four; corpus indexing/warm immutable payload loads are excluded.",
        ],
        "configuration": config,
    }
    for method, values in methods.items():
        report["methods"][method] = {
            "all": summarize(values),
            "by_split": {
                split: summarize([r for r in values if r["split"] == split])
                for split in ("dev", "test")
            },
            "by_split_kind": {
                split: {
                    kind: summarize(
                        [r for r in values if r["split"] == split and r["kind"] == kind]
                    )
                    for kind in ("single", "path", "cross", "comparison", "missing")
                }
                for split in ("dev", "test")
            },
            "by_kind": {
                kind: summarize([r for r in values if r["kind"] == kind])
                for kind in ("single", "path", "cross", "comparison", "missing")
            },
        }
    comparisons = [("vector", "lexical"), ("rrf", "lexical"), ("graph_rrf", "rrf")]
    for left, right in comparisons:
        for split in ("dev", "test"):
            for metric in ("exact_fact_accuracy", "evidence_recall_at_10", "correct_abstention"):
                deltas = []
                for id, values in sorted(by_question.items()):
                    if left not in values or right not in values or values[left]["split"] != split:
                        continue
                    a, b = values[left]["scores"][metric], values[right]["scores"][metric]
                    delta = float(a) - float(b) if a is not None and b is not None else None
                    row = {
                        "question_id": id,
                        "split": split,
                        "kind": values[left]["kind"],
                        "cluster": values[left]["cluster"],
                        "comparison": left + "-" + right,
                        "metric": metric,
                        "delta": delta,
                    }
                    report["paired_deltas"].append(row)
                    deltas.append(row)
                report["family_intervals"][left + "-" + right + "/" + split + "/" + metric] = {
                    "mean_difference": mean(r["delta"] for r in deltas),
                    **cluster_interval(deltas),
                }
    return report
