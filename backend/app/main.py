"""FastAPI application factory.

Wires together configuration, logging, middleware, error handlers, and routers. Keeping this in a
factory (rather than a module-level ``app``) makes the app trivially constructable in tests with
overrides, and keeps import side effects out of the package.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.middleware.request_context import RequestContextMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info("startup", app_env=settings.app_env, version=__version__)
    # Idempotently seed the RBAC catalog so roles/permissions always match the code definitions.
    from app.db.seed import seed_rbac
    from app.db.session import session_scope

    try:
        async with session_scope() as session:
            await seed_rbac(session)
    except Exception:  # pragma: no cover - startup seeding is best-effort in dev
        logger.warning("rbac_seed_skipped_on_startup", exc_info=True)
    yield
    from app.core.http_client import close_http_client

    await close_http_client()
    await dispose_engine()
    await close_redis()
    logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "A lightweight API Gateway + Developer Portal: publish, secure, rate-limit, and "
            "analyze APIs. REST + OpenAPI. Telemetry is emitted for the Observability platform "
            "(Project B)."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Innermost-first: request context wraps everything so ids/logging cover all handlers.
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-Correlation-ID"],
        )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": settings.app_name, "version": __version__, "docs": "/docs"}

    return app


# Uvicorn entrypoint: `uvicorn app.main:app`
app = create_app()
