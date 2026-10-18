import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.agent_integration import router as agent_router
from app.api.operations import router
from app.core.config import get_settings
from app.core.exceptions import DomainError

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Agentic operations platform for Nigerian SMEs.",
)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Return application health for local and deployment verification."""

    return {
        "status": "healthy",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


app.include_router(router)
app.include_router(agent_router)


@app.exception_handler(DomainError)
async def domain_error_handler(request, error: DomainError):
    status = 404 if error.code.endswith("NOT_FOUND") else 409
    return JSONResponse(status_code=status, content={"code": error.code})


@app.exception_handler(psycopg.Error)
async def database_error_handler(request, error):
    return JSONResponse(status_code=503, content={"code": "DATABASE_UNAVAILABLE"})
