import asyncio

from fastapi import Request

from depscope.runtime.errors import DomainError


def services(request: Request):
    value=getattr(request.app.state,"services",None)
    if value is None:
        raise DomainError("SERVICES_NOT_READY", "Database services are not ready",retryable=True)
    return value


async def require_project(container,project_id: str):
    return await asyncio.to_thread(container.snapshots.project,project_id)


async def scoped_snapshot(container,snapshot_id: str,project_id: str | None = None):
    snapshot=await asyncio.to_thread(container.snapshots.load,snapshot_id)
    if project_id is not None and snapshot.project_id!=project_id:
        raise DomainError("SCOPE_MISMATCH", "Snapshot belongs to a different project")
    return snapshot
