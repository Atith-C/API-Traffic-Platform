"""Health and readiness endpoints.

``/health/live``  — process is up (no dependencies checked); use for liveness probes.
``/health/ready`` — dependencies (Postgres, Redis) are reachable; use for readiness probes.
``/health``       — human-friendly aggregate.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.core.redis import get_redis
from app.db.session import get_sessionmaker
from app.schemas.common import HealthComponent, HealthResponse

router = APIRouter(tags=["health"])
logger = structlog.get_logger(__name__)


async def _check_db() -> HealthComponent:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return HealthComponent(status="ok")
    except Exception as exc:  # pragma: no cover - exercised via integration
        logger.warning("health_db_failed", error=str(exc))
        return HealthComponent(status="error", detail="database unreachable")


async def _check_redis() -> HealthComponent:
    try:
        await get_redis().ping()
        return HealthComponent(status="ok")
    except Exception as exc:  # pragma: no cover - exercised via integration
        logger.warning("health_redis_failed", error=str(exc))
        return HealthComponent(status="error", detail="redis unreachable")


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe")
async def ready(response: Response) -> HealthResponse:
    components = {"database": await _check_db(), "redis": await _check_redis()}
    healthy = all(c.status == "ok" for c in components.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=__version__,
        components=components,
    )


@router.get("/health", response_model=HealthResponse, summary="Aggregate health")
async def health(response: Response) -> HealthResponse:
    return await ready(response)
