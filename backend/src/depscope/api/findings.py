import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from depscope.analysis.impact import PathResult
from depscope.analysis.matching import MatchRun
from depscope.runtime.errors import DomainError
from depscope.runtime.pagination import Page

from .dependencies import services

router=APIRouter(tags=["findings"])


@router.get("/api/match-runs/{run_id}",response_model=MatchRun)
async def get_run(run_id: str,container=Depends(services)):
    return await asyncio.to_thread(container.runs.load,run_id)


@router.get("/api/match-runs/{run_id}/findings",response_model=Page)
async def findings(run_id: str,cursor: str | None = None,limit: Annotated[int,Query(ge=1,le=100)]=50,container=Depends(services)):
    return await asyncio.to_thread(container.runs.list_findings,run_id,cursor,limit)


@router.get("/api/findings/{finding_id}/paths",response_model=PathResult)
async def paths(finding_id: str,run_map: str | None = None,container=Depends(services)):
    if run_map is None:
        _,run=await asyncio.to_thread(container.runs.finding,finding_id)
        mapping={run.snapshot_id:run.id}
    else:
        try:
            mapping=json.loads(run_map)
            if not isinstance(mapping,dict) or len(mapping)>50 or not mapping or any(not isinstance(k,str) or not isinstance(v,str) for k,v in mapping.items()):
                raise ValueError
        except (ValueError,TypeError):
            raise DomainError("INVALID_RUN_MAP", "Provide a snapshot-to-run mapping",("/run_map",)) from None
    return await asyncio.to_thread(container.path_service.paths,finding_id,mapping)


@router.get("/api/advisory-revisions/{revision_id}")
async def advisory(revision_id: str,container=Depends(services)):
    revision=await asyncio.to_thread(container.runs.revision,revision_id)
    return revision.model_dump(mode="json")
