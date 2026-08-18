# Architecture

## Overview

A **modular monolith**: one deployable process with strict internal boundaries. This gives us the
operational simplicity of a monolith with the internal decoupling of services — and a clean seam to
split out later if needed. Business logic never lives in route handlers.

```
HTTP ─▶ api/ (routers)  ─▶ services/  ─▶ repositories/ ─▶ models/ (SQLAlchemy)
             │                 │              │
             ▼                 ▼              ▼
          schemas/          core/          db/ (async engine/session)
        (Pydantic DTOs)  (config, security, errors, logging, redis, telemetry)
```

### Layer responsibilities

| Layer | Responsibility | Rules |
|-------|----------------|-------|
| `api/` | Parse/validate the request, call one service, serialize the result. | No business logic. No DB access. |
| `services/` | Business logic, orchestration, authorization decisions. | Framework-agnostic. No FastAPI imports. DI via constructor. |
| `repositories/` | Data access for one aggregate. Enforce tenant scoping. | Only place that touches the ORM/session. |
| `models/` | SQLAlchemy 2.x ORM. UUID PKs + timestamps. | No business logic. |
| `schemas/` | Pydantic v2 request/response DTOs. | Never expose ORM objects directly. |
| `core/` | Config, security, error handling, logging, redis, telemetry emitter. | No feature logic. |
| `workers/` | Celery tasks (rollups, telemetry outbox drain, notifications). | Reuse services/repositories. |

## Key decisions (ADRs in brief)

- **ADR-001 — Async everywhere (FastAPI + SQLAlchemy async + asyncpg).** The platform is I/O-bound
  (a DB + Redis round-trip per request, plus an upstream call on the gateway path). Async gives the
  concurrency a gateway needs without a thread-per-request model.
- **ADR-002 — Repository + Service split with DI.** Services depend on repository *interfaces*, so
  business logic is unit-testable with fakes and independent of FastAPI/SQLAlchemy. Wiring happens at
  the edge via FastAPI `Depends`.
- **ADR-003 — Consistent error envelope.** All errors are `AppError` subclasses rendered by central
  handlers into `{"error": {code, message, details, request_id}}`. Stack traces are never exposed.
- **ADR-004 — Structured logging + request correlation.** structlog with a per-request
  `request_id`/`correlation_id` bound into contextvars. JSON in prod. This is also the first hook for
  Project B.
- **ADR-005 — Transactional outbox for telemetry (added in the Logging milestone).** Request/audit
  events are written to an outbox table in the *same* transaction as the business write, then drained
  asynchronously by a worker through a transport-agnostic `TelemetryEmitter`. No Kafka dependency in
  Project A; a Kafka/Redis-Streams emitter can be added later with zero schema change.
- **ADR-006 — Real gateway, configurable upstreams.** The gateway forwards to real, per-version
  upstream URLs (default demo target: httpbin). Automated tests mock the upstream with `respx` so
  they never hit the network. See [upstreams.md](upstreams.md).

## Request lifecycle (foundation)

1. `RequestContextMiddleware` assigns `request_id`/`correlation_id`, binds them to the log context,
   and emits a structured access log with latency on the way out.
2. CORS middleware (dashboard origins only).
3. Router → (service → repository) → response.
4. Any raised `AppError` (or unexpected exception) is caught by the registered handlers and rendered
   as the standard envelope; `X-Request-ID` is echoed on every response.

## Observability hooks

- `/health/live`, `/health/ready`, `/health` — liveness/readiness for probes.
- `/metrics` — Prometheus exposition.
- Structured logs carry request/correlation ids.
- OpenTelemetry API/SDK are installed as hooks; exporters are wired in when Project B lands.

## Testing strategy

- **Unit** — services/repositories with fakes; no external deps (`pytest -m unit`).
- **Integration/API** — real Postgres + Redis via **Testcontainers**; httpx `AsyncClient` drives the
  ASGI app; the gateway's upstream is mocked with `respx`.
- Each test gets a fresh engine (bound to its own event loop) and truncated tables for isolation.

## Milestones

Foundation → Auth → Organizations/RBAC → API Management → API Keys → Rate Limiting → Logging →
Analytics → Dashboards → Testing → Deployment. Each milestone ships migrations, tests, and docs.
