"""Capped, checkpointed real generation runs; no simulated rows enter the experiment."""

import asyncio
import fcntl
import json
import os
import random
import re
import time
from decimal import Decimal
from pathlib import Path

from depscope.evaluation.benchmark import Question, build_benchmark
from depscope.evaluation.corpus import CorpusManifest
from depscope.evaluation.freeze import canonical, digest, freeze_suite, verify_suite
from depscope.evaluation.metrics import score_answer
from depscope.evaluation.models import ExperimentManifest
from depscope.evaluation.prepare import bind_required_evidence
from depscope.generation.budget import BudgetedGeneration, BudgetLedger, BudgetPolicy
from depscope.generation.deepseek import DeepSeekGeneration
from depscope.generation.pricing import official_price
from depscope.investigation.answers import ModelReply
from depscope.investigation.service import SYSTEM_PROMPT, Investigator
from depscope.retrieval.documents import EvidenceDocument
from depscope.retrieval.embedding import OllamaEmbedding
from depscope.retrieval.indexes import IndexManifest, IndexStore
from depscope.retrieval.retrievers import METHODS, Retriever
from depscope.runtime.config import PROJECT_ROOT, load_settings
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now


class ImmutableCache:
    """Memoize immutable payload reads only. Ranked queries still execute in Neo4j."""

    def __init__(self, target):
        self.target = target
        self.values = {}

    def load(self, id):
        if id not in self.values:
            self.values[id] = self.target.load(id)
        return self.values[id]

    def revision(self, id):
        if ("revision", id) not in self.values:
            self.values[("revision", id)] = self.target.revision(id)
        return self.values[("revision", id)]


class IndexedPayloadCache:
    def __init__(self, store, manifest):
        self.target = store
        self.manifest = manifest
        self.docs = store.documents(manifest)
        self.parts = store.chunks(manifest)

    def documents(self, manifest):
        return self.docs

    def chunks(self, manifest):
        return self.parts

    def lexical(self, *args, **kwargs):
        return self.target.lexical(*args, **kwargs)

    def search(self, *args, **kwargs):
        return self.target.search(*args, **kwargs)


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(canonical(value))
    tmp.replace(path)


def critical_hashes(root):
    files = []
    for folder in ("generation", "investigation", "retrieval"):
        files.extend((Path(root) / "backend/src/depscope" / folder).glob("*.py"))
    files.append(Path(root) / "backend/src/depscope/graph/evidence.py")
    for name in (
        "runner.py",
        "metrics.py",
        "reference.py",
        "benchmark.py",
        "freeze.py",
        "prepare.py",
        "report.py",
    ):
        files.append(Path(root) / "backend/src/depscope/evaluation" / name)
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in sorted(files)}


def freeze_prepared(settings, home):
    home = Path(home)
    manifest = CorpusManifest.model_validate_json(
        (PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes()
    )
    documents = tuple(
        EvidenceDocument.model_validate_json(json.dumps(row))
        for row in json.loads((home / "documents.json").read_bytes())
    )
    from depscope.sources.records import RecordStore

    questions = bind_required_evidence(
        build_benchmark(manifest), documents, RecordStore(settings.data_root)
    )
    index = IndexManifest.model_validate_json((home / "index.json").read_bytes())
    price = official_price(settings.deepseek_base_url, settings.generation_model)
    if price is None:
        raise DomainError(
            "PRICE_UNAVAILABLE", "Batch evaluation requires recorded monetary pricing"
        )
    config = {
        "corpus_digest": manifest.id,
        "corpus_manifest_sha256": digest(
            (PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes()
        ),
        "index": index.model_dump(mode="json"),
        "generation_model": settings.generation_model,
        "provider_base_url": settings.deepseek_base_url,
        "thinking": "disabled",
        "output_tokens": 1024,
        "system_prompt": SYSTEM_PROMPT,
        "response_schema": ModelReply.model_json_schema(),
        "evidence_files": {
            name: digest((home / name).read_bytes())
            for name in ("documents.json", "chunks.json", "index.json")
        },
        "software_source_hashes": critical_hashes(PROJECT_ROOT),
        "retrieval": {
            "methods": list(METHODS),
            "ranked_candidates": 50,
            "rrf_k": 60,
            "graph_seed_chunks": 4,
            "graph_extra_chunks": 6,
            "graph_hops": 1,
            "max_chunks": 10,
            "max_text_characters": 12000,
            "chunk_characters": 2000,
            "overlap_characters": 200,
            "exact_locator_shared": True,
            "immutable_payload_cache": True,
        },
        "price": price.model_dump(mode="json"),
        "budget": {"currency": "USD", "max_amount": "10", "max_calls": 1200},
        "seed": 20261013,
        "concurrency": 4,
        "bootstrap_replicates": 1000,
        "empty_context_final_generation": True,
        "label_origin": "program_reference",
        "human_semantic_audit": False,
        "latency_environment": {
            "os": "macOS",
            "architecture": "arm64",
            "python": "3.11.5",
            "memory_gib": 16,
            "cpu_cores": 8,
            "generation": "remote DeepSeek API",
            "embedding": "local Qwen GPU",
            "warmup": "corpus index preparation excluded; query embedding included; immutable DB payload reads cached before timed calls",
        },
        "protocol": "v1; parameters selected before any dev/test generation, no performance tuning between splits",
    }
    suite = freeze_suite(questions, config, home)
    return suite


class ExperimentRunner:
    def __init__(self, container, settings, output=None):
        self.container, self.settings = container, settings
        self.output = Path(output or PROJECT_ROOT / "artifacts/experiments")
        self.ledger = BudgetLedger(
            container.driver, official_price(settings.deepseek_base_url, settings.generation_model)
        )

    async def run(self, suite, methods=METHODS, run_id="benchmark-v1-20261014"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
            raise DomainError("INVALID_RUN", "Use a bounded experiment identifier")
        target = self.output / run_id
        target.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target / ".run.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DomainError(
                    "EXPERIMENT_BUSY", "Another local runner owns this experiment"
                ) from None
            return await self._run(suite, methods, run_id)
        finally:
            os.close(descriptor)

    async def _run(self, suite, methods, run_id):
        verify_suite(suite)
        home = Path(suite.output_path)
        config = json.loads((home / "config.json").read_bytes())
        if tuple(methods) != tuple(config["retrieval"]["methods"]):
            raise DomainError("FROZEN_SUITE_MODIFIED", "Methods differ from frozen configuration")
        if (
            critical_hashes(PROJECT_ROOT) != config["software_source_hashes"]
            or self.settings.generation_model != config["generation_model"]
            or self.settings.deepseek_base_url != config["provider_base_url"]
        ):
            raise DomainError(
                "FROZEN_SUITE_MODIFIED",
                "Software/model/provider changed; require a recorded evaluation version",
            )
        for name, hash in config["evidence_files"].items():
            if digest((home / name).read_bytes()) != hash:
                raise DomainError("FROZEN_SUITE_MODIFIED", "Frozen evidence was modified")
        if (
            digest((PROJECT_ROOT / "artifacts/corpus/manifest.json").read_bytes())
            != config["corpus_manifest_sha256"]
        ):
            raise DomainError("FROZEN_SUITE_MODIFIED", "Corpus manifest differs")
        policy = BudgetPolicy(
            currency="USD",
            max_amount=Decimal(config["budget"]["max_amount"]),
            max_calls=config["budget"]["max_calls"],
        )
        self.ledger.open_run(run_id, policy)
        target = self.output / run_id
        target.mkdir(parents=True, exist_ok=True)
        manifest_path = target / "manifest.json"
        # Recover a completed publication from the authoritative CAS/DB anchor, without regenerating.
        with self.container.driver.session() as session:
            anchor = session.run(
                "MATCH (r:ExperimentRun {run_id:$id}) RETURN r.manifest_digest AS manifest_digest,r.report_digest AS report_digest",
                id=run_id,
            ).single()
        if anchor:
            original = self.container.records.get(anchor["manifest_digest"])
            recorded = ExperimentManifest.model_validate_json(original)
            if recorded.suite_digest != suite.digest:
                raise DomainError(
                    "EXPERIMENT_CONTEXT_MISMATCH", "Existing experiment belongs to another suite"
                )
            if (
                manifest_path.exists()
                and digest(manifest_path.read_bytes()) != anchor["manifest_digest"]
            ):
                raise DomainError("EXPERIMENT_IMMUTABLE", "Published experiment was modified")
            manifest_path.write_bytes(original)
            report_path = target / "report.json"
            if not report_path.exists():
                report_path.write_bytes(self.container.records.get(anchor["report_digest"]))
            from depscope.evaluation.experiments import ExperimentRepository

            ExperimentRepository(self.output, self.ledger, self.container.records).load(run_id)
            if recorded.status != "complete":
                raise DomainError(
                    "EXPERIMENT_INCOMPLETE",
                    "Recorded incomplete run is immutable; create an explicitly recorded new version",
                )
            return recorded
        if (
            manifest_path.exists()
            and json.loads(manifest_path.read_bytes())["suite_digest"] != suite.digest
        ):
            raise DomainError(
                "EXPERIMENT_CONTEXT_MISMATCH", "This run already belongs to another frozen suite"
            )
        if manifest_path.exists():
            recorded = ExperimentManifest.model_validate_json(manifest_path.read_bytes())
            if recorded.status == "complete":
                from depscope.evaluation.experiments import ExperimentRepository

                ExperimentRepository(self.output, self.ledger, self.container.records).load(run_id)
                return recorded
        questions = tuple(
            Question.model_validate_json(json.dumps(row))
            for row in json.loads((home / "questions.json").read_bytes())
        )
        index = IndexManifest.model_validate_json((home / "index.json").read_bytes())
        store = IndexStore(self.container.driver)
        cached_store = IndexedPayloadCache(store, index)
        snapshots = ImmutableCache(self.container.snapshots)
        runs = ImmutableCache(self.container.runs)
        comparisons = ImmutableCache(self.container.comparisons)
        # Warm only immutable DB payloads, never reference answers or generated responses.
        for q in questions:
            for sid, rid in q.scope.run_map.items():
                snapshots.load(sid)
                for revision in runs.load(rid).revision_ids:
                    runs.revision(revision)
            if q.scope.comparison_id:
                comparisons.load(q.scope.comparison_id)
        retriever = Retriever(
            cached_store,
            index,
            OllamaEmbedding(self.settings.embedding_url, self.settings.embedding_model),
            snapshots,
            runs,
            comparisons,
        )
        provider = DeepSeekGeneration(
            self.settings.deepseek_api_key,
            self.settings.deepseek_base_url,
            self.settings.generation_model,
        )
        investigator = Investigator(
            retriever, BudgetedGeneration(provider, self.ledger), records=self.container.records
        )
        existing = {}
        for file in sorted((target / "results").glob("*.json")):
            row = json.loads(file.read_bytes())
            if row["suite_digest"] != suite.digest or row["question_id"] not in {
                q.id for q in questions
            }:
                raise DomainError(
                    "EXPERIMENT_CONTEXT_MISMATCH", "Checkpoint differs from frozen suite"
                )
            existing[(row["question_id"], row["method"])] = row
        semaphore = asyncio.Semaphore(config["concurrency"])
        done = len(existing)

        async def execute(question, method, order):
            nonlocal done
            if (question.id, method) in existing:
                return
            async with semaphore:
                started = now()
                begin = time.perf_counter()
                answer = await investigator.answer(
                    question.prompt, question.scope, method, run_id, evaluation_generate_empty=True
                )
                elapsed = time.perf_counter() - begin
                row = {
                    "run_id": run_id,
                    "suite_digest": suite.digest,
                    "question_id": question.id,
                    "kind": question.kind,
                    "split": question.split,
                    "family_names": list(question.family_names),
                    "cluster": "|".join(question.family_names),
                    "method": method,
                    "order": order,
                    "started_at": started,
                    "finished_at": now(),
                    "latency_seconds": elapsed,
                    "answer": answer.model_dump(mode="json"),
                    "scores": score_answer(question.model_dump(mode="json"), answer),
                }
                path = target / "results" / (question.id + "-" + method + ".json")
                atomic(path, row)
                existing[(question.id, method)] = row
                done += 1
                if done % 10 == 0:
                    print(
                        json.dumps(
                            {
                                "run_id": run_id,
                                "completed": done,
                                "planned": len(questions) * len(methods),
                                "last_status": answer.status,
                            }
                        ),
                        flush=True,
                    )

        for split in ("dev", "test"):
            tasks = [(q, method) for q in questions if q.split == split for method in methods]
            rng = random.Random(config["seed"] + (0 if split == "dev" else 1))
            rng.shuffle(tasks)
            await asyncio.gather(
                *(execute(q, method, index) for index, (q, method) in enumerate(tasks))
            )
            atomic(
                target / (split + "-checkpoint.json"),
                {
                    "run_id": run_id,
                    "suite_digest": suite.digest,
                    "completed": sum(row["split"] == split for row in existing.values()),
                    "budget": self.ledger.summary(run_id).model_dump(mode="json"),
                    "observed_at": now(),
                },
            )
            print(
                json.dumps(
                    {
                        "stage": split + "_complete",
                        "run_id": run_id,
                        "rows": len(existing),
                        "budget": self.ledger.summary(run_id).model_dump(mode="json"),
                    }
                ),
                flush=True,
            )
        rows = tuple(existing.values())
        hashes = {
            file.name: digest(file.read_bytes())
            for file in sorted((target / "results").glob("*.json"))
        }
        budget = self.ledger.summary(run_id)
        calls = self.ledger.calls(run_id)
        atomic(
            target / "call-ledger.json",
            {
                "run_id": run_id,
                "summary": budget.model_dump(mode="json"),
                "calls": calls,
                "observed_at": now(),
            },
        )
        failures = tuple(
            {
                "question_id": r["question_id"],
                "method": r["method"],
                "status": r["answer"]["status"],
            }
            for r in rows
            if r["answer"]["status"] not in ("answered", "insufficient_evidence")
        )
        from depscope.evaluation.report import make_report

        report = make_report(rows, config)
        atomic(target / "report.json", report)
        usage = {
            "prompt_tokens": sum(
                (r["answer"].get("usage") or {}).get("prompt_tokens", 0) for r in rows
            ),
            "completion_tokens": sum(
                (r["answer"].get("usage") or {}).get("completion_tokens", 0) for r in rows
            ),
            "rows_with_usage": sum(r["answer"].get("usage") is not None for r in rows),
            "actual_reserved_calls": budget.call_count,
            "planned_final_generations": len(questions) * len(methods),
        }
        complete = len(rows) == len(questions) * len(methods) and budget.call_count >= len(
            questions
        ) * len(methods)
        manifest = ExperimentManifest(
            id=run_id,
            run_id=run_id,
            suite_digest=suite.digest,
            status="complete" if complete else "incomplete",
            method_results=report["methods"],
            usage=usage,
            cost=budget.model_dump(mode="json"),
            failures=failures,
            result_hashes=hashes,
            observed_at=now(),
        )
        atomic(manifest_path, manifest.model_dump(mode="json"))
        manifest_source = self.container.records.put(
            manifest_path.read_bytes(), "derived://depscope/experiment-v1", now()
        )
        report_source = self.container.records.put(
            (target / "report.json").read_bytes(), "derived://depscope/experiment-report-v1", now()
        )
        with self.container.driver.session() as session:
            anchor = session.run(
                "MERGE (r:ExperimentRun {run_id:$id}) ON CREATE SET r.suite_digest=$suite,r.manifest_digest=$manifest,r.report_digest=$report RETURN r.manifest_digest AS manifest_digest,r.report_digest AS report_digest",
                id=run_id,
                suite=suite.digest,
                manifest=manifest_source.digest,
                report=report_source.digest,
            ).single()
            if (
                anchor["manifest_digest"] != manifest_source.digest
                or anchor["report_digest"] != report_source.digest
            ):
                raise DomainError(
                    "EXPERIMENT_IMMUTABLE", "Recorded experiment cannot be overwritten"
                )
        print(
            json.dumps(
                {
                    "stage": "finished",
                    "run_id": run_id,
                    "status": manifest.status,
                    "usage": usage,
                    "cost": budget.model_dump(mode="json"),
                }
            ),
            flush=True,
        )
        if not complete:
            raise DomainError(
                "EXPERIMENT_INCOMPLETE",
                "Final rows or actual generation calls are missing; failures were preserved",
            )
        return manifest


if __name__ == "__main__":
    from depscope.api.services import build_services

    settings = load_settings()
    container = build_services(settings)
    try:
        home = PROJECT_ROOT / "artifacts/benchmark/v1"
        suite = freeze_prepared(settings, home)
        asyncio.run(ExperimentRunner(container, settings).run(suite))
    finally:
        container.close()
