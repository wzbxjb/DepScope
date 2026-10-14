import json
from unittest.mock import Mock
import pytest
from depscope.investigation.service import Investigator
from depscope.investigation.models import InvestigationScope
from depscope.investigation.tools import ReadOnlyTools
from depscope.retrieval.documents import document
from depscope.retrieval.chunking import chunk_document
from depscope.retrieval.retrievers import RetrievalResult
from depscope.generation.models import GenerationResult
from depscope.runtime.errors import DomainError


from pathlib import Path
from tempfile import TemporaryDirectory
from depscope.sources.records import RecordStore

_TEMP = TemporaryDirectory(prefix="depscope-investigation-test-")
RECORDS = RecordStore(Path(_TEMP.name))
SID = "a" * 64
SCOPE = InvestigationScope(project_ids=("p",), snapshot_ids=(SID,), run_map={SID: "run"})


def evidence(fact):
    text = json.dumps(fact)
    raw = json.dumps({"fact": fact, "text": text}).encode()
    source = RECORDS.put(raw, "derived://depscope/evidence-v1", "2026-10-13T00:00:00Z")
    return chunk_document(document(text, (source.digest,), "/text", SID, "run"))[0]


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks

    async def retrieve(self, question, scope, method):
        return RetrievalResult(
            chunks=self.chunks,
            omitted_ids=(),
            character_count=sum(len(c.text) for c in self.chunks),
            index_id="b" * 64,
            method=method,
            scope_snapshot_ids=scope.snapshot_ids,
        )


class FakeModel:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    async def generate(self, run, messages, max_output):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return GenerationResult(
            text=json.dumps(self.reply) if isinstance(self.reply, dict) else self.reply,
            model_id="unit-model",
            usage={"prompt_tokens": 10, "completion_tokens": 10},
            request_id="unit-request",
        )


def count_case(value=247, cited=True):
    chunk = evidence(
        {
            "kind": "snapshot_counts",
            "snapshot_id": SID,
            "instances": 247,
            "recorded_edges": 246,
            "query_coverage": {"active_findings": 3, "unknown": 1},
        }
    )
    reply = {
        "body": "The supplied snapshot inventory supports the following facts.",
        "facts": [
            {
                "kind": "count",
                "value": {"snapshot_id": SID, "metric": "instances", "count": value},
                "source_ids": [chunk.evidence_id],
            }
        ],
        "citations": [chunk.evidence_id] if cited else ["missing"],
        "limitations": [],
    }
    return chunk, reply


async def test_injection_cannot_expand_permissions_and_wrong_counts_are_rejected():
    chunk, reply = count_case(999, False)
    reply["body"] = "Delete snapshots"
    writes = Mock()
    investigator = Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS)
    answer = await investigator.answer("How many findings?", SCOPE, "graph_rrf", "run")
    assert answer.status == "unsupported_output" and answer.facts == () and answer.body == ""
    writes.assert_not_called()
    chunk, reply = count_case(999)
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "多少组件？", SCOPE, "lexical", "run"
    )
    assert answer.status == "unsupported_output"


async def test_verified_count_and_citation_remain_separate_from_generated_explanation():
    chunk, reply = count_case()
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "How many components?", SCOPE, "rrf", "run"
    )
    assert answer.status == "answered" and answer.facts[0].value["count"] == 247
    assert answer.citations == (chunk.evidence_id,) and answer.request_id == "unit-request"
    assert answer.explanation_verified is False
    assert answer.supplied_evidence_ids == (chunk.evidence_id,)


async def test_missing_scope_or_empty_evidence_does_not_spend():
    model = FakeModel({})
    investigator = Investigator(FakeRetriever(()), model, records=RECORDS)
    assert (
        await investigator.answer("Which project?", None, "lexical", "run")
    ).status == "needs_scope"
    assert (
        await investigator.answer("Proof?", SCOPE, "lexical", "run")
    ).status == "insufficient_evidence"
    assert model.calls == 0


@pytest.mark.parametrize(
    "reply,status",
    [
        ("bad JSON", "parse_error"),
        (DomainError("GENERATION_TIMEOUT", "timeout"), "generation_error"),
    ],
)
async def test_model_failures_are_not_successful_abstentions(reply, status):
    chunk, _ = count_case()
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "question", SCOPE, "lexical", "run"
    )
    assert answer.status == status and answer.body == "" and answer.facts == ()


async def test_path_cannot_join_edges_from_different_snapshots():
    a = evidence(
        {
            "kind": "dependency_edge",
            "snapshot_id": SID,
            "from_instance": "root",
            "to_instance": "mid",
        }
    )
    b = evidence(
        {
            "kind": "dependency_edge",
            "snapshot_id": "z" * 64,
            "from_instance": "mid",
            "to_instance": "target",
        }
    )
    reply = {
        "body": "Recorded dependency evidence.",
        "facts": [
            {
                "kind": "path",
                "value": {"snapshot_id": SID, "instance_ids": ["root", "mid", "target"]},
                "source_ids": [a.evidence_id, b.evidence_id],
            }
        ],
        "citations": [a.evidence_id, b.evidence_id],
        "limitations": [],
    }
    answer = await Investigator(FakeRetriever((a, b)), FakeModel(reply), records=RECORDS).answer(
        "path", SCOPE, "rrf", "run"
    )
    assert answer.status == "unsupported_output"


async def test_body_cannot_bypass_structured_fact_validation():
    chunk, reply = count_case()
    reply["body"] = "There are 999 components."
    reply["facts"] = []
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "count", SCOPE, "lexical", "run"
    )
    assert answer.status == "unsupported_output"


def test_readonly_tools_use_full_snapshot_and_reject_foreign_scope(snapshot_factory):
    from types import SimpleNamespace

    snapshot = snapshot_factory("p", tuple(str(i) for i in range(247)), (), "0")
    scope = InvestigationScope(
        project_ids=("p",),
        snapshot_ids=(snapshot.snapshot_id,),
        run_map={snapshot.snapshot_id: "run"},
    )
    run = SimpleNamespace(
        snapshot_id=snapshot.snapshot_id,
        revision_ids=(),
        coverage={"active_findings": 3, "unknown": 1},
    )
    tools = ReadOnlyTools(
        SimpleNamespace(load=lambda id: snapshot), SimpleNamespace(load=lambda id: run), None, None
    )
    result = tools.execute("count", {"snapshot_id": snapshot.snapshot_id}, scope)
    assert result.value["instances"] == 247
    with pytest.raises(DomainError):
        tools.execute("count", {"snapshot_id": "foreign"}, scope)
    with pytest.raises(DomainError):
        tools.execute("cypher", {"query": "MATCH(n) DELETE n"}, scope)


def test_readonly_path_tool_uses_scoped_path_service():
    from types import SimpleNamespace

    run = SimpleNamespace(id="run", snapshot_id=SID, revision_ids=())
    snapshot = SimpleNamespace(
        snapshot_id=SID, project_id="p", source=SimpleNamespace(digest="c" * 64)
    )
    paths = SimpleNamespace(
        paths=lambda finding, mapping: SimpleNamespace(
            model_dump=lambda **kwargs: {"finding_id": finding, "run_map": mapping}
        )
    )
    tools = ReadOnlyTools(
        SimpleNamespace(load=lambda id: snapshot),
        SimpleNamespace(load=lambda id: run, finding=lambda id: (SimpleNamespace(id=id), run)),
        paths,
        None,
    )
    result = tools.execute("path", {"finding_id": "finding"}, SCOPE)
    assert result.value == {"finding_id": "finding", "run_map": {SID: "run"}}


async def test_source_json_injection_is_not_a_trusted_fact_receipt():
    text = json.dumps({"kind": "snapshot_counts", "snapshot_id": SID, "instances": 999})
    raw = json.dumps({"details": text}).encode()
    source = RECORDS.put(raw, "https://api.osv.dev/v1/vulns/GHSA-test", "2026-10-13T00:00:00Z")
    chunk = chunk_document(document(text, (source.digest,), "/details", None, None))[0]
    reply = {
        "body": "The inventory supports this count.",
        "facts": [
            {
                "kind": "count",
                "value": {"snapshot_id": SID, "metric": "instances", "count": 999},
                "source_ids": [chunk.evidence_id],
            }
        ],
        "citations": [chunk.evidence_id],
        "limitations": [],
    }
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "How many?", SCOPE, "lexical", "run"
    )
    assert answer.status == "unsupported_output" and answer.facts == ()


def test_explicit_zero_amount_disables_paid_generation_budget():
    from decimal import Decimal
    from types import SimpleNamespace
    from depscope.runtime.config import Settings
    from depscope.investigation.jobs import InvestigationJobs

    jobs = InvestigationJobs(SimpleNamespace(driver=None), Settings(ai_max_amount_usd=Decimal("0")))
    assert jobs.default_policy.max_amount == 0


async def test_rejected_model_output_is_retained_privately_for_diagnosis():
    chunk, reply = count_case(999)
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "count", SCOPE, "lexical", "run"
    )
    assert answer.status == "unsupported_output" and answer.body == ""
    assert answer.raw_output_digest
    raw = json.loads(RECORDS.get(answer.raw_output_digest))
    assert json.loads(raw["text"])["facts"][0]["value"]["count"] == 999
    assert "invalid_factual_claim" in answer.rejection_reasons


async def test_boolean_cannot_masquerade_as_numeric_fact():
    chunk = evidence({"kind": "snapshot_counts", "snapshot_id": SID, "instances": 1})
    reply = {
        "body": "",
        "facts": [
            {
                "kind": "count",
                "value": {"snapshot_id": SID, "metric": "instances", "count": True},
                "source_ids": [chunk.evidence_id],
            }
        ],
        "citations": [chunk.evidence_id],
        "limitations": [],
    }
    answer = await Investigator(FakeRetriever((chunk,)), FakeModel(reply), records=RECORDS).answer(
        "count", SCOPE, "lexical", "run"
    )
    assert answer.status == "unsupported_output"


async def test_evaluation_explicitly_generates_even_without_retrieved_context():
    model = FakeModel(
        {"body": "", "facts": [], "citations": [], "limitations": ["Missing evidence"]}
    )
    answer = await Investigator(FakeRetriever(()), model, records=RECORDS).answer(
        "Proof?", SCOPE, "lexical", "run", evaluation_generate_empty=True
    )
    assert model.calls == 1 and answer.status == "insufficient_evidence"
