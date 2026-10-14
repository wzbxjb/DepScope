import asyncio

from fastapi import APIRouter, Depends

from .dependencies import services
from .imports import JobSubmitted

router=APIRouter(prefix="/api/demo",tags=["demo"])


@router.post("/public-sample",status_code=202,response_model=JobSubmitted)
async def public_sample(container=Depends(services)):
    job=await asyncio.to_thread(container.jobs.enqueue,"sample",{})
    return JobSubmitted(job_id=job.id)
