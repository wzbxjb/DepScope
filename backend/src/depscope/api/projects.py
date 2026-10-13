import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from depscope.runtime.pagination import Page

from .dependencies import services

router=APIRouter(prefix="/api/projects",tags=["projects"])


class ProjectInput(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    name: str = Field(min_length=1,max_length=200)


@router.post("",status_code=201)
async def create_project(body: ProjectInput,container=Depends(services)):
    id=await asyncio.to_thread(container.snapshots.create_project,body.name)
    return {"id":id}


@router.get("",response_model=Page)
async def list_projects(cursor: str | None = None,limit: Annotated[int,Query(ge=1,le=100)]=50,container=Depends(services)):
    return await asyncio.to_thread(container.snapshots.list_projects,cursor,limit)
