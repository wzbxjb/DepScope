from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import DomainError


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="DepScope", version="0.1.0")
    app.state.settings = settings

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        status = 413 if exc.code == "LIMIT_EXCEEDED" else 400
        return JSONResponse(status_code=status, content={"error": exc.as_dict()})

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    return app
