import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from neo4j.exceptions import DriverError, Neo4jError

from .config import Settings
from .errors import DomainError


def error_status(code: str) -> int:
    if code in {"UPLOAD_TOO_LARGE","LIMIT_EXCEEDED"}:
        return 413
    if code.endswith("NOT_FOUND"):
        return 404
    if code in {"SCOPE_MISMATCH","SNAPSHOT_BUSY","IDENTICAL_SNAPSHOTS","VERIFICATION_CONTEXT_MISMATCH"} or code.endswith("CONTEXT_MISMATCH"):
        return 409
    if code in {"SERVICES_NOT_READY","DATABASE_NOT_CONFIGURED"}:
        return 503
    if code=="UNSUPPORTED_MEDIA_TYPE":
        return 415
    return 422


def create_app(settings: Settings,services=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        if app.state.services is None and settings.neo4j_uri:
            from depscope.api.services import build_services
            try:
                app.state.services=await asyncio.to_thread(build_services,settings)
            except (DomainError,DriverError,Neo4jError):
                app.state.services=None
        yield
        if app.state.services is not None:
            await asyncio.to_thread(app.state.services.close)
    app=FastAPI(title="DepScope",version="0.1.0",lifespan=lifespan)
    app.state.settings=settings
    app.state.services=services

    @app.middleware("http")
    async def local_mutations(request: Request,call_next):
        origin=request.headers.get("origin")
        if origin and request.method not in {"GET","HEAD","OPTIONS"}:
            try:
                parsed=urlsplit(origin)
                allowed=parsed.scheme in {"http","https"} and parsed.hostname in {"localhost","127.0.0.1","::1"}
            except ValueError:
                allowed=False
            if not allowed:
                return JSONResponse(status_code=403,content={"error":DomainError("ORIGIN_REJECTED","Use the local application to submit changes").as_dict()})
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request,exc: DomainError):
        return JSONResponse(status_code=error_status(exc.code),content={"error":exc.as_dict()})

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request,exc: RequestValidationError):
        pointers=tuple("/"+"/".join(str(v) for v in error["loc"][1:]) for error in exc.errors())
        return JSONResponse(status_code=422,content={"error":DomainError("REQUEST_VALIDATION_ERROR","Invalid request fields",pointers).as_dict()})

    @app.get("/health/live")
    def live():
        return {"status":"alive"}

    @app.get("/health/ready")
    async def ready():
        configured=settings.public_summary()
        available=app.state.services is not None
        if available:
            try:
                await asyncio.to_thread(app.state.services.driver.verify_connectivity)
            except (DriverError,Neo4jError):
                available=False
        return JSONResponse(status_code=200 if available else 503,content={"status":"ready" if available else "degraded",
                    "database":"ready" if available else "unavailable","sources":"not_probed",
                    "generation":"configured" if configured["generation_configured"] else "not_configured",
                    "embedding":"configured" if configured["embedding_configured"] else "not_configured"})

    from depscope.api import comparisons, demo, experiments, findings, imports, investigations, jobs, projects, snapshots
    for module in (projects,imports,jobs,snapshots,findings,comparisons,demo,investigations,experiments):
        app.include_router(module.router)
    return app
