"""Shared test fixtures.

Integration/API tests run against **real Postgres and Redis** spun up once per session via
Testcontainers. The schema is created with ``Base.metadata.create_all`` (fast; migrations are
verified separately). Each test gets a clean database via table truncation between tests, so tests
are isolated and order-independent.

If no Docker runtime is available the container fixtures are skipped with a clear message rather
than failing the whole suite — unit tests (no external deps) still run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (register every model on Base.metadata before create_all)
from app.core.config import Settings
from app.db.base import Base

try:  # Testcontainers is optional at import time so unit-only runs don't need Docker.
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    _HAS_TESTCONTAINERS = True
except Exception:  # pragma: no cover
    _HAS_TESTCONTAINERS = False


def _docker_available() -> bool:
    import shutil
    import subprocess

    if not _HAS_TESTCONTAINERS or shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=10)
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker runtime not available; integration tests require Postgres/Redis containers.",
)


@pytest.fixture(scope="session")
def _pg_container() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker not available")
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def _redis_container() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker not available")
    with RedisContainer("redis:7-alpine") as rc:
        host = rc.get_container_host_ip()
        port = rc.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def test_settings(_pg_container: str, _redis_container: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=_pg_container,
        redis_url=_redis_container,
        jwt_secret="test-secret-do-not-use-in-prod-0123456789abcdef",
        log_json=False,
        debug=True,
    )


@pytest_asyncio.fixture
async def _engine(test_settings: Settings) -> AsyncIterator:
    """Function-scoped engine bound to the running test's event loop.

    asyncpg connection pools are tied to the loop that created them, so a session-scoped engine
    would fail with "attached to a different loop". A fresh engine per test is cheap; the schema is
    (idempotently) created and every table is truncated on teardown for isolation.
    """
    engine = create_async_engine(test_settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed the RBAC catalog so tests have the built-in roles/permissions available.
    from app.db.seed import seed_rbac

    async with async_sessionmaker(engine, expire_on_commit=False)() as seed_session:
        await seed_rbac(seed_session)
        await seed_session.commit()
    try:
        yield engine
    finally:
        table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        if table_names:
            async with engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(_engine) -> AsyncIterator[AsyncSession]:
    """A clean session per test."""
    maker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def redis_client(_redis_container: str) -> AsyncIterator:
    """A flushed Redis client per test (isolates rate-limit / quota counters)."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(_redis_container, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def client(
    _engine, _redis_container: str, test_settings: Settings
) -> AsyncIterator[AsyncClient]:
    """An httpx AsyncClient bound to the app, wired to the containerized DB/Redis."""
    import redis.asyncio as aioredis

    from app.core import redis as redis_module
    from app.db import session as session_module
    from app.main import create_app

    session_module._engine = _engine
    session_module._sessionmaker = async_sessionmaker(
        _engine, expire_on_commit=False, autoflush=False
    )
    redis_module._client = aioredis.from_url(_redis_container, decode_responses=True)
    await redis_module._client.flushdb()  # isolate rate-limit / quota / throttle counters

    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await redis_module._client.aclose()
        redis_module._client = None
        session_module._engine = None
        session_module._sessionmaker = None
