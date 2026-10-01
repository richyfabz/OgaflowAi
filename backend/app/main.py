from fastapi import FastAPI

from app.core.config import get_settings


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
