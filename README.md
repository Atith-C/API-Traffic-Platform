# API Traffic Management Platform

A production-grade, lightweight **API Gateway + Developer Portal** — publish, secure, rate-limit,
meter, and analyze APIs. Inspired in spirit by Kong / Tyk / Apigee, built as a clean modular
monolith and designed so its telemetry feeds a companion Observability platform (Project B) with no
schema changes.

> Status: **Complete (all 11 milestones)** — independently runnable & deployable. 90 tests passing,
> 85% coverage, deployment verified end-to-end. See [docs/HANDOFF.md](docs/HANDOFF.md).

## What it does

- **Organizations, users, RBAC** — multi-tenant, role-based access control.
- **API management** — register APIs, version them, point each version at a real upstream.
- **API keys** — issue (shown once), rotate, revoke.
- **Gateway** — authenticate by API key, enforce rate limits + quotas, forward to the upstream,
  measure latency, and record every request.
- **Rate limiting** — fixed-window / sliding-window / token-bucket, backed by Redis.
- **Analytics & dashboards** — usage, errors, top endpoints, active keys.
- **Telemetry** — every request/audit event is written through a transactional outbox behind a
  transport-agnostic emitter, ready to stream to the Observability platform later.

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL · Redis · Celery · Alembic ·
structlog · Prometheus · Docker. Tests: pytest + httpx + Testcontainers.

## Architecture

Modular monolith with strict layering — business logic never lives in route handlers:

```
api  →  services  →  repositories  →  models
              ↘ schemas (DTOs)   ↘ core (config, security, errors, telemetry)
```

See [docs/architecture.md](docs/architecture.md) for the full picture and ADRs.

> **New to backend?** Start with [docs/START_HERE.md](docs/START_HERE.md) — a beginner's on-ramp
> (plain-English overview, a [concepts glossary](docs/CONCEPTS.md), and a [guided code tour](docs/CODE_TOUR.md)).

## Quick start (Docker)

```bash
docker compose -f infra/docker-compose.yml up --build   # if this errors, use: docker-compose
# API:    http://localhost:8000  ·  Docs: /docs  ·  Portal UI: http://localhost:5173
```

Then fill it with data (prints a login email + password for the portal):

```bash
cd backend && pip install -e ".[dev]" && python -m scripts.seed_traffic
```

## Local development

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                     # adjust DATABASE_URL / REDIS_URL if needed
alembic upgrade head
uvicorn app.main:app --reload
```

## Testing

Integration tests use **Testcontainers** and need a running Docker daemon (Colima works headlessly
on macOS: `colima start`).

```bash
cd backend
pytest                 # full suite
pytest -m unit         # fast, no Docker required
pytest -m integration  # real Postgres + Redis via Testcontainers
```

## Project layout

```
backend/    FastAPI app, workers, migrations, tests
frontend/   Minimal React + Vite dashboard (added in the Dashboards milestone)
infra/      Dockerfile + docker-compose
docs/       Architecture, ADRs, telemetry contract, upstream references
telemetry/  Versioned telemetry event contract (shared with Project B)
```

## License

MIT
