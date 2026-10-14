import asyncio

from fastapi import APIRouter, Depends

from depscope.api.dependencies import services
from depscope.evaluation.experiments import ExperimentRepository
from depscope.runtime.config import PROJECT_ROOT

router = APIRouter(tags=["experiments"])


def repository(container):
    return ExperimentRepository(
        PROJECT_ROOT / "artifacts/experiments", container.investigation.ledger, container.records
    )


@router.get("/api/experiments")
async def listing(cursor: str | None = None, limit: int = 50, container=Depends(services)):
    page = await asyncio.to_thread(repository(container).list, cursor, limit)
    return page


@router.get("/api/experiments/{id}")
async def details(id: str, container=Depends(services)):
    return await asyncio.to_thread(repository(container).load, id)
