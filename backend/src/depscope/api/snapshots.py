import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from depscope.graph.queries import GraphView
from depscope.ingest.models import Snapshot
from depscope.runtime.pagination import Page

from .dependencies import require_project, scoped_snapshot, services
from .imports import JobSubmitted

router=APIRouter(tags=["snapshots"])


@router.get("/api/projects/{project_id}/snapshots",response_model=Page)
async def list_snapshots(project_id: str,cursor: str | None = None,limit: Annotated[int,Query(ge=1,le=100)]=50,container=Depends(services)):
    await require_project(container,project_id)
    return await asyncio.to_thread(container.snapshots.list_snapshots,project_id,cursor,limit)


@router.get("/api/snapshots/{snapshot_id}",response_model=Snapshot)
async def get_snapshot(snapshot_id: str,project_id: str | None = None,container=Depends(services)):
    return await scoped_snapshot(container,snapshot_id,project_id)


@router.get("/api/snapshots/{snapshot_id}/graph",response_model=GraphView)
async def graph(snapshot_id: str,focus_id: str | None = None,run_id: str | None = None,
                project_id: str | None = None,container=Depends(services)):
    await scoped_snapshot(container,snapshot_id,project_id)
    return await asyncio.to_thread(container.graph_service.view,snapshot_id,focus_id,run_id)


@router.get("/api/snapshots/{snapshot_id}/match-runs",response_model=Page)
async def list_runs(snapshot_id: str,cursor: str | None = None,limit: Annotated[int,Query(ge=1,le=100)]=50,container=Depends(services)):
    await scoped_snapshot(container,snapshot_id)
    return await asyncio.to_thread(container.runs.list_runs,snapshot_id,cursor,limit)


@router.post("/api/snapshots/{snapshot_id}/match-runs",status_code=202,response_model=JobSubmitted)
async def match(snapshot_id: str,container=Depends(services)):
    snapshot=await scoped_snapshot(container,snapshot_id)
    job=await asyncio.to_thread(container.jobs.enqueue,"match",{"snapshot_ids":[snapshot_id]})
    return JobSubmitted(job_id=job.id,project_id=snapshot.project_id)
