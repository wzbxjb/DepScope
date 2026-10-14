import json
import re
from typing import Literal

from pydantic import Field

from depscope.ingest.models import Contract


class ToolFact(Contract):
    kind: Literal["count", "version", "path", "query", "advisory", "comparison"]
    value: dict
    source_ids: tuple[str, ...]


class ModelReply(Contract):
    body: str = Field(max_length=10000)
    facts: tuple[ToolFact, ...]
    citations: tuple[str, ...]
    limitations: tuple[str, ...]


class Answer(Contract):
    status: str
    body: str = ""
    facts: tuple[ToolFact, ...] = ()
    citations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    model_id: str | None = None
    request_id: str | None = None
    usage: dict | None = None
    explanation_verified: bool = False
    supplied_evidence_ids: tuple[str, ...] = ()
    omitted_evidence_ids: tuple[str, ...] = ()
    index_id: str | None = None
    method: str | None = None
    tool_facts: tuple[ToolFact, ...] = ()
    raw_output_digest: str | None = None
    rejection_reasons: tuple[str, ...] = ()


def validate_citations(ids, supplied):
    return bool(ids) and set(ids) <= {c.evidence_id for c in supplied}


def trusted_receipts(chunks, records, scope):
    facts = {}
    if records is None:
        return facts
    for chunk in chunks:
        try:
            source = chunk.source_ids[0]
            if not any(
                s.uri == "derived://depscope/evidence-v1" for s in records.observations(source)
            ):
                continue
            receipt = json.loads(records.get(source))
            if (
                chunk.pointer != "/text"
                or chunk.start != 0
                or receipt["text"] != chunk.text
                or chunk.end != len(chunk.text)
            ):
                continue
            fact = receipt["fact"]
            if (
                fact.get("snapshot_id") not in scope.snapshot_ids
                and fact.get("kind") != "comparison"
            ):
                continue
            facts[chunk.evidence_id] = fact
        except (KeyError, ValueError, TypeError):
            continue
    return facts


def supported_facts(receipts):
    supported = []
    for id, fact in receipts.items():
        sid = fact.get("snapshot_id")
        kind = fact.get("kind")
        if kind == "snapshot_counts":
            for metric in ("instances", "unique_package_versions", "recorded_edges"):
                if metric in fact:
                    supported.append(
                        ToolFact(
                            kind="count",
                            value={"snapshot_id": sid, "metric": metric, "count": fact[metric]},
                            source_ids=(id,),
                        )
                    )
            for metric, value in fact.get("query_coverage", {}).items():
                supported.append(
                    ToolFact(
                        kind="count",
                        value={
                            "snapshot_id": sid,
                            "metric": "query_coverage." + metric,
                            "count": value,
                        },
                        source_ids=(id,),
                    )
                )
        elif kind == "component":
            coordinate = fact["component"].get("coordinate")
            if coordinate:
                supported.append(
                    ToolFact(
                        kind="version",
                        value={
                            "snapshot_id": sid,
                            "instance_id": fact["instance_id"],
                            "package": coordinate["name"],
                            "version": coordinate["raw_version"],
                        },
                        source_ids=(id,),
                    )
                )
        elif kind == "package_query":
            query = fact["query"]
            supported.append(
                ToolFact(
                    kind="query",
                    value={
                        "snapshot_id": sid,
                        "package": query["coordinate"]["name"],
                        "version": query["coordinate"]["raw_version"],
                        "status": query["status"],
                    },
                    source_ids=(id,),
                )
            )
        elif kind == "dependency_edge":
            supported.append(
                ToolFact(
                    kind="path",
                    value={
                        "snapshot_id": sid,
                        "instance_ids": [fact["from_instance"], fact["to_instance"]],
                    },
                    source_ids=(id,),
                )
            )
        elif kind == "comparison":
            c = fact["comparison"]
            for metric in (
                "level",
                "removed_known_matches",
                "added_known_matches",
                "remaining_known_matches",
                "unknown",
            ):
                if c.get(metric) is not None:
                    supported.append(
                        ToolFact(
                            kind="comparison",
                            value={"comparison_id": c["id"], "metric": metric, "value": c[metric]},
                            source_ids=(id,),
                        )
                    )
    return tuple(supported)


def valid_fact(claim, supported, receipts, scope):
    if not claim.source_ids or not set(claim.source_ids) <= set(receipts):
        return False
    if claim.kind != "path":
        return any(
            claim.kind == s.kind
            and json.dumps(claim.value, sort_keys=True) == json.dumps(s.value, sort_keys=True)
            and set(s.source_ids) <= set(claim.source_ids)
            for s in supported
        )
    if (
        set(claim.value) != {"snapshot_id", "instance_ids"}
        or claim.value["snapshot_id"] not in scope.snapshot_ids
    ):
        return False
    path = claim.value["instance_ids"]
    if (
        not isinstance(path, list)
        or not 2 <= len(path) <= 201
        or any(not isinstance(v, str) for v in path)
    ):
        return False
    edges = {
        (r["from_instance"], r["to_instance"])
        for id, r in receipts.items()
        if id in claim.source_ids
        and r.get("kind") == "dependency_edge"
        and r.get("snapshot_id") == claim.value["snapshot_id"]
    }
    return all(pair in edges for pair in zip(path, path[1:], strict=False))


def qualitative_body(body):
    # Precise values belong in checked facts; do not permit a free-text numeric bypass.
    without_ids = re.sub(
        r"GHSA-[a-z0-9-]+|CVE-\d{4}-\d+|[0-9a-f]{64}", "", body, flags=re.IGNORECASE
    )
    return not re.search(r"\d|->|→", without_ids)
