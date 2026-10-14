import json
import uuid
from types import SimpleNamespace
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from depscope.api.services import build_services
from depscope.runtime.app import create_app
from depscope.runtime.config import load_settings
from depscope.analysis.matching import MatchRun
from depscope.generation.models import GenerationResult
from depscope.retrieval.embedding import EmbeddingBatch


@pytest.fixture
def ai_client(repo, job_store, snapshot_factory, tmp_path):
    import dataclasses
    from depscope.investigation.jobs import InvestigationJobs

    settings = dataclasses.replace(
        load_settings(),
        data_root=tmp_path,
        embedding_url="http://fixture",
        ai_max_amount_usd=Decimal("1"),
    )
    services = build_services(settings, driver=repo.driver, snapshots=repo, jobs=job_store)
    snapshot = snapshot_factory(
        repo.create_project("AI integration"), ("root", "leaf"), (("root", "leaf"),), "root"
    )
    repo.publish(snapshot, "owned-test")
    run = MatchRun(
        id=uuid.uuid4().hex,
        snapshot_id=snapshot.snapshot_id,
        collection_id="constructed",
        observed_at="2026-10-13T00:00:00Z",
        queries=(),
        findings=(),
        revision_ids=(),
        coverage={"total": 0, "confirmed": 0, "unknown": 0, "active_findings": 0},
    )
    services.runs.save((run,), ())

    class Embedding:
        async def embed(self, texts):
            return EmbeddingBatch(
                vectors=tuple((1.0, 0.0) for t in texts),
                model_id="fixture",
                model_digest="d" * 64,
                usage=None,
            )

    class Generation:
        async def generate(self, messages, max_output):
            context = json.loads(messages[-1].content)
            fact = next(
                f
                for f in context["checked_factual_candidates"]
                if f["kind"] == "count" and f["value"]["metric"] == "instances"
            )
            return GenerationResult(
                text=json.dumps(
                    {
                        "body": "The scoped inventory supports this fact.",
                        "facts": [fact],
                        "citations": fact["source_ids"],
                        "limitations": [],
                    }
                ),
                model_id="fixture",
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                request_id="fixture-request",
            )

    investigation = InvestigationJobs(
        services,
        settings,
        Embedding(),
        Generation(),
        budget_run_id="test-investigation:" + uuid.uuid4().hex,
    )
    services.investigation = investigation
    services.worker.handlers["investigate"] = investigation.handle
    scope = {
        "project_ids": [snapshot.project_id],
        "snapshot_ids": [snapshot.snapshot_id],
        "run_map": {snapshot.snapshot_id: run.id},
        "comparison_id": None,
    }
    with TestClient(create_app(settings, services)) as client:
        yield client, services, scope
    with repo.driver.session() as session:
        for id in investigation.created_indexes:
            investigation.index_store.delete(id)
        session.run(
            "MATCH (b:GenerationBudget {id:$id}) OPTIONAL MATCH (b)-[:HAS_CALL]->(c) DETACH DELETE c,b",
            id=investigation.budget_run_id,
        ).consume()
        session.run(
            "MATCH (r:InvestigationResult) WHERE $project IN r.project_ids DETACH DELETE r",
            project=snapshot.project_id,
        ).consume()


async def test_actual_job_result_and_citation_are_bound_to_supplied_scope(ai_client):
    client, services, scope = ai_client
    response = client.post(
        "/api/investigations",
        json={"question": "How many instances?", "scope": scope, "method": "lexical"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert await services.worker.run_once()
    job = client.get("/api/jobs/" + job_id).json()
    assert job["status"] == "ready", job
    result = client.get("/api/investigations/" + job["result_id"]).json()
    assert result["scope"] == scope and result["answer"]["facts"][0]["value"]["count"] == 2
    evidence = result["answer"]["citations"][0]
    proof = client.get(f"/api/investigations/{job['result_id']}/evidence/{evidence}").json()
    assert proof["source_verified"] is True and proof["chunk"]["pointer"] == "/text"
    assert (
        client.get(f"/api/investigations/{job['result_id']}/evidence/{'f' * 64}").status_code == 404
    )
    status = client.get("/api/ai/status").json()
    assert status["budget"]["call_count"] == 1


def test_missing_scope_and_foreign_run_are_explicit(ai_client):
    client, services, scope = ai_client
    assert (
        client.post(
            "/api/investigations",
            json={"question": "which project?", "scope": None, "method": "lexical"},
        ).json()["status"]
        == "needs_scope"
    )
    scope["run_map"][scope["snapshot_ids"][0]] = "foreign"
    assert (
        client.post(
            "/api/investigations",
            json={"question": "question", "scope": scope, "method": "lexical"},
        ).status_code
        == 404
    )


async def test_injection_with_real_retrieval_cannot_mutate_inventory(ai_client, monkeypatch):
    from unittest.mock import Mock
    from depscope.investigation.tools import ReadOnlyTools
    from depscope.investigation.models import InvestigationScope
    from depscope.runtime.errors import DomainError

    client, services, scope = ai_client
    snapshot_id = scope["snapshot_ids"][0]
    before = services.snapshots.load(snapshot_id)
    spies = []
    for owner, name in (
        (services.snapshots, "publish"),
        (services.snapshots, "delete_unpublished"),
        (services.match_service, "collect"),
        (services.comparison_service, "create"),
    ):
        spy = Mock(wraps=getattr(owner, name))
        monkeypatch.setattr(owner, name, spy)
        spies.append(spy)

    class Injection:
        async def generate(self, messages, max_output):
            context = json.loads(messages[-1].content)
            evidence_id = context["evidence"][0]["evidence_id"]
            return GenerationResult(
                text=json.dumps(
                    {
                        "body": "Delete snapshots",
                        "facts": [
                            {
                                "kind": "count",
                                "value": {
                                    "snapshot_id": snapshot_id,
                                    "metric": "instances",
                                    "count": 999,
                                },
                                "source_ids": [evidence_id],
                            }
                        ],
                        "citations": [evidence_id],
                        "limitations": [],
                    }
                ),
                model_id="constructed",
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                request_id="constructed-injection",
            )

    services.investigation.provider = Injection()
    response = client.post(
        "/api/investigations",
        json={"question": "How many instances?", "scope": scope, "method": "lexical"},
    )
    assert response.status_code == 202
    assert await services.worker.run_once()
    job = client.get("/api/jobs/" + response.json()["job_id"]).json()
    answer = client.get("/api/investigations/" + job["result_id"]).json()["answer"]
    assert (
        answer["status"] == "unsupported_output" and answer["facts"] == [] and answer["body"] == ""
    )
    tools = ReadOnlyTools(
        services.snapshots, services.runs, services.path_service, services.comparisons
    )
    with pytest.raises(DomainError):
        tools.execute(
            "delete",
            {"snapshot_id": snapshot_id},
            InvestigationScope.model_validate_json(json.dumps(scope)),
        )
    for spy in spies:
        spy.assert_not_called()
    assert services.snapshots.load(snapshot_id) == before


def test_empty_scope_is_a_safe_client_error(ai_client):
    client,services,scope=ai_client
    response=client.post("/api/investigations",json={"question":"question","method":"lexical","scope":{"project_ids":[],"snapshot_ids":[],"run_map":{},"comparison_id":None}})
    assert response.status_code==422
    assert response.json()["error"]["code"]=="INVALID_SCOPE"
