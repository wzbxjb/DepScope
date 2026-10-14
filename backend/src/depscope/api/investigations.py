import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from depscope.graph.investigations import InvestigationRecord
from depscope.investigation.answers import Answer
from depscope.investigation.models import InvestigationScope, validate_scope
from depscope.runtime.errors import DomainError

from .dependencies import services

router = APIRouter(tags=["investigations"])


class ScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_ids: list[str]
    snapshot_ids: list[str]
    run_map: dict[str, str]
    comparison_id: str | None = None

    def to_scope(self):
        return InvestigationScope(
            project_ids=tuple(self.project_ids),
            snapshot_ids=tuple(self.snapshot_ids),
            run_map=self.run_map,
            comparison_id=self.comparison_id,
        )


class InvestigationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=5000)
    scope: ScopeInput | None = None
    method: Literal["lexical", "vector", "rrf", "graph_rrf"] = "graph_rrf"


@router.post("/api/investigations", status_code=202)
async def submit(body: InvestigationInput, request: Request, container=Depends(services)):
    if body.scope is None:
        return Answer(
            status="needs_scope",
            limitations=("Select explicit projects, snapshots and query runs.",),
        )
    try:
        scope = body.scope.to_scope()
    except ValidationError:
        raise DomainError(
            "INVALID_SCOPE",
            "Select nonempty projects, snapshots and exactly one run per snapshot",
            ("/scope",),
        ) from None
    await asyncio.to_thread(
        validate_scope, scope, container.snapshots, container.runs, container.comparisons
    )
    if not request.app.state.settings.public_summary()["generation_configured"]:
        raise DomainError("GENERATION_NOT_CONFIGURED", "Configure your private model API key")
    if container.investigation.embedding is None:
        raise DomainError("EMBEDDING_NOT_CONFIGURED", "Configure the local embedding model")
    job = await asyncio.to_thread(
        container.jobs.enqueue,
        "investigate",
        {"question": body.question, "scope": scope.model_dump(mode="json"), "method": body.method},
    )
    return {"job_id": job.id}


@router.get("/api/investigations/{id}", response_model=InvestigationRecord)
async def result(id: str, container=Depends(services)):
    return await asyncio.to_thread(container.investigation.results.load, id)


@router.get("/api/investigations/{id}/evidence/{evidence_id}")
async def evidence(id: str, evidence_id: str, container=Depends(services)):
    return await asyncio.to_thread(container.investigation.evidence, id, evidence_id)


@router.get("/api/ai/status")
async def status(request: Request, container=Depends(services)):
    settings = request.app.state.settings
    try:
        budget = (
            await asyncio.to_thread(
                container.investigation.ledger.summary, container.investigation.budget_run_id
            )
        ).model_dump(mode="json")
    except DomainError as exc:
        if exc.code != "BUDGET_NOT_FOUND":
            raise
        policy = container.investigation.default_policy
        budget = {
            "call_count": 0,
            "remaining_calls": policy.max_calls,
            "estimated_spent": None,
            "currency": policy.currency,
            "remaining": str(policy.max_amount),
            "unknown_usage_calls": 0,
            "max_amount": str(policy.max_amount),
            "max_calls": policy.max_calls,
        }
    return {
        "generation": "configured"
        if settings.public_summary()["generation_configured"]
        else "not_configured",
        "embedding": "configured" if container.investigation.embedding else "not_configured",
        "budget": budget,
    }


class LimitIncrease(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_amount_usd: str = Field(max_length=32)
    max_calls: int = Field(ge=0, le=100000)


@router.post("/api/ai/limits")
async def increase(body: LimitIncrease, container=Depends(services)):
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(body.max_amount_usd)
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
    except InvalidOperation:
        raise DomainError("INVALID_AMOUNT", "Amount must be finite and non-negative") from None
    await asyncio.to_thread(container.investigation.ensure_budget)
    return await asyncio.to_thread(
        container.investigation.ledger.increase_limits,
        container.investigation.budget_run_id,
        amount,
        body.max_calls,
    )
