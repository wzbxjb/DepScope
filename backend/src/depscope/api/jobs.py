import asyncio

from fastapi import APIRouter, Depends

from .dependencies import services

router=APIRouter(prefix="/api/jobs",tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: str,container=Depends(services)):
    job=await asyncio.to_thread(container.jobs.get,job_id)
    return job.model_dump(mode="json",exclude={"payload","owner_token"})


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str,container=Depends(services)):
    await asyncio.to_thread(container.jobs.request_cancel,job_id)
    return await get_job(job_id,container)


@router.post("/{job_id}/retry",status_code=202)
async def retry_job(job_id: str,container=Depends(services)):
    from depscope.runtime.errors import DomainError
    job=await asyncio.to_thread(container.jobs.get,job_id)
    if job.status=="interrupted":
        await asyncio.to_thread(container.jobs.transition,job_id,"interrupted","queued")
        return {"job_id":job_id}
    if job.status=="failed" and job.error and job.error.get("retryable"):
        new=await asyncio.to_thread(container.jobs.enqueue,job.kind,job.payload)
        return {"job_id":new.id}
    raise DomainError("JOB_NOT_RETRYABLE", "This job cannot be retried")
