import asyncio
import json
from decimal import Decimal

from depscope.generation.budget import BudgetedGeneration, BudgetLedger, BudgetPolicy
from depscope.generation.deepseek import DeepSeekGeneration
from depscope.generation.pricing import official_price
from depscope.graph.evidence import EvidenceBuilder, build_index
from depscope.graph.investigations import InvestigationRecord, InvestigationRepository
from depscope.retrieval.embedding import OllamaEmbedding
from depscope.retrieval.indexes import IndexStore
from depscope.retrieval.retrievers import Retriever
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now

from .models import InvestigationScope, validate_scope
from .service import Investigator


class InvestigationJobs:
    def __init__(
        self, services, settings, embedding=None, generation=None, budget_run_id="interactive-v1"
    ):
        self.services, self.settings = services, settings
        self.embedding = embedding or (
            OllamaEmbedding(settings.embedding_url, settings.embedding_model)
            if settings.embedding_url
            else None
        )
        self.provider = generation or DeepSeekGeneration(
            settings.deepseek_api_key, settings.deepseek_base_url, settings.generation_model
        )
        self.ledger = BudgetLedger(
            services.driver, official_price(settings.deepseek_base_url, settings.generation_model)
        )
        self.budget_run_id = budget_run_id
        self.default_policy = BudgetPolicy(
            currency="USD",
            max_amount=settings.ai_max_amount_usd
            if settings.ai_max_amount_usd is not None
            else Decimal("0.10"),
            max_calls=min(20, settings.ai_max_calls),
        )
        self.index_store = IndexStore(services.driver)
        self.results = InvestigationRepository(services.driver)
        self.created_indexes = []

    def ensure_budget(self):
        try:
            return self.ledger.summary(self.budget_run_id)
        except DomainError as exc:
            if exc.code != "BUDGET_NOT_FOUND":
                raise
            self.ledger.open_run(self.budget_run_id, self.default_policy)
            return self.ledger.summary(self.budget_run_id)

    async def handle(self, job, cancelled):
        if self.embedding is None:
            raise DomainError("EMBEDDING_NOT_CONFIGURED", "Configure the local embedding service")
        scope = InvestigationScope.model_validate_json(json.dumps(job.payload["scope"]))
        await asyncio.to_thread(
            validate_scope,
            scope,
            self.services.snapshots,
            self.services.runs,
            self.services.comparisons,
        )
        await asyncio.to_thread(
            self.services.jobs.transition, job.id, "validating", "fetching", job.owner_token
        )
        if cancelled():
            raise DomainError("CANCELLED", "Investigation cancelled before indexing")
        builder = EvidenceBuilder(
            self.services.snapshots,
            self.services.runs,
            self.services.comparisons,
            self.services.records,
        )
        documents = await asyncio.to_thread(builder.build, scope)
        manifest = await build_index(documents, self.embedding, self.index_store)
        self.created_indexes.append(manifest.id)
        if cancelled():
            raise DomainError("CANCELLED", "Investigation cancelled before generation")
        await asyncio.to_thread(self.ensure_budget)
        retriever = Retriever(
            self.index_store,
            manifest,
            self.embedding,
            self.services.snapshots,
            self.services.runs,
            self.services.comparisons,
        )

        class Capture:
            result = None

            async def retrieve(capture, *args):
                capture.result = await retriever.retrieve(*args)
                return capture.result

        capture = Capture()
        investigator = Investigator(
            capture, BudgetedGeneration(self.provider, self.ledger), records=self.services.records
        )
        answer = await investigator.answer(
            job.payload["question"], scope, job.payload["method"], self.budget_run_id
        )
        if cancelled():
            raise DomainError(
                "CANCELLED",
                "Investigation cancelled before publication; persisted usage is retained",
            )
        await asyncio.to_thread(
            self.services.jobs.transition, job.id, "fetching", "writing", job.owner_token
        )
        record = InvestigationRecord(
            id=job.id,
            question=job.payload["question"],
            scope=scope,
            answer=answer,
            evidence_chunks=capture.result.chunks if capture.result else (),
            observed_at=now(),
        )
        await asyncio.to_thread(self.results.save, record)
        return record.id

    def evidence(self, record_id, evidence_id):
        record = self.results.load(record_id)
        chunk = next((c for c in record.evidence_chunks if c.evidence_id == evidence_id), None)
        if chunk is None:
            raise DomainError(
                "EVIDENCE_NOT_FOUND", "Evidence was not supplied to this investigation"
            )
        raw = json.loads(self.services.records.get(chunk.source_ids[0]))
        value = raw
        try:
            for token in chunk.pointer.lstrip("/").split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if isinstance(value, list) else value[token]
        except (ValueError, KeyError, IndexError, TypeError):
            raise DomainError(
                "EVIDENCE_LOCATION_INVALID", "Original source field is unavailable"
            ) from None
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True)
        )
        excerpt = text[chunk.start : chunk.end]
        if excerpt != chunk.text:
            raise DomainError(
                "EVIDENCE_LOCATION_INVALID", "Indexed chunk does not match its source field"
            )
        return {
            "chunk": chunk.model_dump(mode="json"),
            "source_verified": True,
            "original_field_excerpt": excerpt,
            "source_observations": [
                s.model_dump(mode="json")
                for s in self.services.records.observations(chunk.source_ids[0])
            ],
            "upstream_source_ids": list(chunk.source_ids[1:]),
            "upstream_pointer": raw.get("fact", {}).get("upstream_pointer"),
        }
