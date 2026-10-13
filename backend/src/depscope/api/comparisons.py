import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from depscope.analysis.comparison import Comparison

from .dependencies import scoped_snapshot, services
from .imports import JobSubmitted

router=APIRouter(prefix="/api/comparisons",tags=["comparisons"])


class ComparisonInput(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    baseline_id: str
    candidate_id: str
    verification_id: str | None = Field(default=None,pattern=r"^[0-9a-f]{64}$")


@router.post("",status_code=202,response_model=JobSubmitted)
async def compare(body: ComparisonInput,container=Depends(services)):
    await scoped_snapshot(container,body.baseline_id)
    await scoped_snapshot(container,body.candidate_id)
    job=await asyncio.to_thread(container.jobs.enqueue,"compare",body.model_dump())
    return JobSubmitted(job_id=job.id)


@router.get("/{comparison_id}",response_model=Comparison)
async def get_comparison(comparison_id: str,container=Depends(services)):
    return await asyncio.to_thread(container.comparisons.load,comparison_id)
