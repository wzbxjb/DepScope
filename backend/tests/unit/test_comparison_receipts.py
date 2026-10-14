import json

from depscope.analysis.comparison import Comparison
from depscope.graph.evidence import EvidenceBuilder
from depscope.investigation.answers import supported_facts, trusted_receipts
from depscope.investigation.models import InvestigationScope
from depscope.retrieval.chunking import chunk_document
from depscope.runtime.config import PROJECT_ROOT
from depscope.sources.records import RecordStore


def test_large_comparison_preserves_individually_checkable_scalar_receipts(tmp_path):
    manifest = json.loads((PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes())
    comparison = Comparison.model_validate_json(
        (
            PROJECT_ROOT
            / "artifacts/corpus/comparisons"
            / (manifest["comparison_ids"][0] + ".json")
        ).read_bytes()
    )
    records = RecordStore(tmp_path)
    builder = EvidenceBuilder(None, None, None, records)
    docs = builder.comparison_receipts(comparison, ("a" * 64, "b" * 64))
    scope = InvestigationScope(
        project_ids=("p",),
        snapshot_ids=(comparison.baseline_id, comparison.candidate_id),
        run_map=dict(zip((comparison.baseline_id, comparison.candidate_id), comparison.run_ids, strict=True)),
        comparison_id=comparison.id,
    )
    facts = supported_facts(
        trusted_receipts(tuple(c for doc in docs for c in chunk_document(doc)), records, scope)
    )
    assert {f.value["metric"] for f in facts} == {
        "level",
        "removed_known_matches",
        "added_known_matches",
        "remaining_known_matches",
        "unknown",
    }
    assert all(doc.comparison_id == comparison.id for doc in docs)


def test_comparison_lineage_preserves_upstream_records_without_expanding_prompt_metadata(tmp_path):
    manifest = json.loads((PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes())
    comparison = Comparison.model_validate_json(
        (
            PROJECT_ROOT
            / "artifacts/corpus/comparisons"
            / (manifest["comparison_ids"][0] + ".json")
        ).read_bytes()
    )
    records = RecordStore(tmp_path)
    builder = EvidenceBuilder(None, None, None, records)
    upstream = tuple(str(i).zfill(64) for i in range(100))
    documents = builder.comparison_receipts(comparison, upstream)
    assert all(len(d.source_ids) <= 4 for d in documents)
    lineage = json.loads(records.get(documents[0].source_ids[-1]))
    assert (
        tuple(lineage["upstream_source_ids"]) == upstream
        and lineage["comparison_id"] == comparison.id
    )
