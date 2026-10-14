import json
import uuid
from dataclasses import replace

import pytest

from depscope.api.services import build_services
from depscope.evaluation.benchmark import Question
from depscope.evaluation.freeze import canonical, digest, freeze_suite
from depscope.evaluation.runner import ExperimentRunner, critical_hashes
from depscope.generation.models import GenerationResult
from depscope.graph.evidence import EvidenceBuilder
from depscope.ingest.cyclonedx import parse_cyclonedx
from depscope.investigation.models import InvestigationScope
from depscope.retrieval.chunking import chunk_document
from depscope.retrieval.embedding import EmbeddingBatch
from depscope.retrieval.indexes import IndexStore, make_manifest
from depscope.runtime.config import PROJECT_ROOT, load_settings
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now


class Embedding:
    async def embed(self, texts):
        return EmbeddingBatch(
            vectors=tuple((1.0, 0.1) for _ in texts),
            model_id="constructed-embedding",
            model_digest="test-fixed-model",
            usage=None,
        )


class OfflineGeneration:
    calls = 0

    async def generate(self, messages, max_output):
        type(self).calls += 1
        return GenerationResult(
            text=json.dumps(
                {
                    "body": "",
                    "facts": [],
                    "citations": [],
                    "limitations": ["Constructed offline fixture"],
                }
            ),
            model_id="constructed-offline-generation",
            request_id=str(uuid.uuid4()),
            usage={"prompt_tokens": 10, "completion_tokens": 10},
        )


async def setup(repo, job_store, tmp_path, mock_osv, monkeypatch, max_calls):
    settings = replace(load_settings(), data_root=tmp_path / "runtime")
    container = build_services(settings, driver=repo.driver, snapshots=repo, jobs=job_store)
    # MockOsv's real record writer is redirected to this controlled test store.
    mock_osv.client.records = container.records
    raw = canonical(
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "application",
                    "name": "test-only-app",
                    "version": "1.0",
                    "bom-ref": "root",
                }
            },
            "components": [
                {"type": "library", "name": "requests", "version": "2.32.3", "bom-ref": "lib"}
            ],
            "dependencies": [
                {"ref": "root", "dependsOn": ["lib"]},
                {"ref": "lib", "dependsOn": []},
            ],
        }
    )
    source = container.records.put(raw, "fixture://constructed-evaluation", now())
    project = repo.create_project("constructed experiment runner")
    snapshot = parse_cyclonedx(raw, project, source, {})
    repo.publish(snapshot, "fixture-" + uuid.uuid4().hex)
    from depscope.analysis.matching import MatchService

    mock_osv.batch([{}, {}])
    runs = await MatchService(repo, container.runs, mock_osv.client).collect(
        (snapshot.snapshot_id,), uuid.uuid4().hex
    )
    run = runs[snapshot.snapshot_id]
    scope = InvestigationScope(
        project_ids=(project,),
        snapshot_ids=(snapshot.snapshot_id,),
        run_map={snapshot.snapshot_id: run.id},
    )
    documents = EvidenceBuilder(
        repo, container.runs, container.comparisons, container.records
    ).build(scope)
    chunks = tuple(c for d in documents for c in chunk_document(d))
    batch = await Embedding().embed(tuple(c.text for c in chunks))
    manifest = make_manifest(chunks, batch, "constructed-test")
    IndexStore(repo.driver).write(manifest, chunks, batch.vectors, documents)
    home = tmp_path / "suite"
    home.mkdir()
    (home / "index.json").write_bytes(canonical(manifest.model_dump(mode="json")))
    question = Question(
        id=digest(snapshot.snapshot_id.encode()),
        kind="missing",
        split="dev",
        family_names=("constructed-family",),
        scope=scope,
        prompt="Constructed offline evaluation fixture",
        source_ids=(source.digest,),
        expected_facts=(),
        reference_locators=(),
    )
    config = {
        "corpus_digest": "test-only-corpus",
        "corpus_manifest_sha256": digest(
            (PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes()
        ),
        "software_source_hashes": critical_hashes(PROJECT_ROOT),
        "generation_model": settings.generation_model,
        "provider_base_url": settings.deepseek_base_url,
        "retrieval": {"methods": ["lexical", "vector", "rrf", "graph_rrf"]},
        "evidence_files": {"index.json": digest((home / "index.json").read_bytes())},
        "budget": {"max_amount": "1", "max_calls": max_calls},
        "seed": 20261013,
        "concurrency": 2,
    }
    suite = freeze_suite((question,), config, home)
    monkeypatch.setattr("depscope.evaluation.runner.OllamaEmbedding", lambda *args: Embedding())
    monkeypatch.setattr(
        "depscope.evaluation.runner.DeepSeekGeneration", lambda *args: OfflineGeneration()
    )
    return container, settings, suite, manifest


async def test_runner_enforces_actual_persistent_call_cap(
    repo, job_store, tmp_path, mock_osv, monkeypatch
):
    container, settings, suite, index = await setup(
        repo, job_store, tmp_path, mock_osv, monkeypatch, 1
    )
    runner = ExperimentRunner(container, settings, tmp_path / "results")
    runid = "constructed-cap-" + uuid.uuid4().hex
    OfflineGeneration.calls = 0
    with pytest.raises(DomainError, match="EXPERIMENT_INCOMPLETE"):
        await runner.run(suite, run_id=runid)
    assert runner.ledger.summary(runid).call_count == 1 and OfflineGeneration.calls == 1
    rows = list((tmp_path / "results" / runid / "results").glob("*.json"))
    assert (
        len(rows) == 4
        and sum(json.loads(p.read_bytes())["answer"]["status"] == "budget_exhausted" for p in rows)
        == 3
    )
    IndexStore(repo.driver).delete(index.id)


async def test_completed_experiment_recovers_manifest_without_repeating_paid_calls(
    repo, job_store, tmp_path, mock_osv, monkeypatch
):
    container, settings, suite, index = await setup(
        repo, job_store, tmp_path, mock_osv, monkeypatch, 10
    )
    runner = ExperimentRunner(container, settings, tmp_path / "results")
    runid = "constructed-resume-" + uuid.uuid4().hex
    OfflineGeneration.calls = 0
    first = await runner.run(suite, run_id=runid)
    (tmp_path / "results" / runid / "manifest.json").unlink()
    recovered = await runner.run(suite, run_id=runid)
    assert recovered == first and OfflineGeneration.calls == 4
    IndexStore(repo.driver).delete(index.id)


async def test_only_one_runner_can_charge_the_same_experiment(
    repo, job_store, tmp_path, mock_osv, monkeypatch
):
    import asyncio

    container, settings, suite, index = await setup(
        repo, job_store, tmp_path, mock_osv, monkeypatch, 10
    )
    original = OfflineGeneration.generate

    async def delayed(self, *args):
        await asyncio.sleep(0.1)
        return await original(self, *args)

    monkeypatch.setattr(OfflineGeneration, "generate", delayed)
    runner = ExperimentRunner(container, settings, tmp_path / "results")
    runid = "constructed-lock-" + uuid.uuid4().hex
    first = asyncio.create_task(runner.run(suite, run_id=runid))
    await asyncio.sleep(0.03)
    try:
        with pytest.raises(DomainError, match="EXPERIMENT_BUSY"):
            await runner.run(suite, run_id=runid)
    finally:
        await first
        IndexStore(repo.driver).delete(index.id)
