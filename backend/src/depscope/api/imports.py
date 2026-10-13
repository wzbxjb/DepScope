import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from depscope.identity.coordinates import identify
from depscope.ingest.limits import async_read_limited
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import now
from depscope.sources.depsdev import dependencies_uri

from .dependencies import require_project, services

router=APIRouter(prefix="/api/projects",tags=["imports"])


class JobSubmitted(BaseModel):
    job_id: str
    project_id: str | None = None


class PublicResolutionInput(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    name: str = Field(min_length=1,max_length=200)
    version: str = Field(min_length=1,max_length=200)


@router.post("/{project_id}/imports",status_code=202,response_model=JobSubmitted)
async def upload(project_id: str,request: Request,container=Depends(services)):
    await require_project(container,project_id)
    if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "Upload CycloneDX JSON as application/json")
    raw=await async_read_limited(request.stream())
    source=await asyncio.to_thread(container.records.put,raw,"upload://local-sbom",now())
    job=await asyncio.to_thread(container.jobs.enqueue,"import",{"project_id":project_id,"digest":source.digest,
                              "source_kind":"observed_environment","environment":{},"source_ref":source.model_dump(mode="json")})
    return JobSubmitted(job_id=job.id,project_id=project_id)


@router.post("/{project_id}/public-resolutions",status_code=202,response_model=JobSubmitted)
async def public_resolution(project_id: str,body: PublicResolutionInput,container=Depends(services)):
    await require_project(container,project_id)
    coordinate=identify(body.name,body.version,None)
    if coordinate is None:
        raise DomainError("INVALID_COORDINATE", "Use an exact, parseable PyPI package version",("/version",))
    job=await asyncio.to_thread(container.jobs.enqueue,"import",{"project_id":project_id,
                              "uri":dependencies_uri(coordinate),"source_kind":"public_resolution"})
    return JobSubmitted(job_id=job.id,project_id=project_id)
