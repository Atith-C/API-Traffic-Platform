# Project A — Reproduction Spec (give this to any LLM to rebuild it)

> **Prompt to the LLM:** You are a senior backend engineer. Build the following production-quality
> project exactly as specified, milestone by milestone. After each milestone: write tests and make
> them pass (real infra via Testcontainers), run `ruff` + `mypy` clean, and verify each DB migration
> with `upgrade→downgrade→upgrade`. Do not skip tests. Do not commit to git unless asked.

## 1. What to build
A **lightweight API Gateway + Developer Portal** (spirit of Kong/Tyk/Apigee). Organizations register
APIs, mint API keys, and route real traffic through a gateway that authenticates the key, enforces
rate limits + quotas, forwards to a configurable real upstream, measures latency, records the
request, and emits **versioned telemetry** through a **transactional outbox** (so a companion
observability product can consume it with zero schema changes).

## 2. Stack (pin these choices)
Python 3.12 · FastAPI (async) · SQLAlchemy 2.x async + asyncpg · PostgreSQL · Redis · Celery (+beat) ·
Alembic (async env) · Argon2id (argon2-cffi) · PyJWT (HS256) · httpx · structlog · orjson ·
Prometheus client · OpenTelemetry hooks. Tests: pytest + pytest-asyncio + httpx AsyncClient +
**Testcontainers (Postgres, Redis)** + respx. Lint/type: ruff + mypy. Minimal React+Vite+TS+Tailwind+
React Query frontend. Docker multi-stage + docker-compose + GitHub Actions.

## 3. Architecture (rules)
Modular monolith, strict layering: `api/ → services/ → repositories/ → models/`, with `schemas/`
(Pydantic DTOs) and `core/` (config, security, errors, logging, redis, telemetry) as side rails.
**Business logic never in route handlers. The ORM is only touched inside repositories.** DI at the
edge via FastAPI `Depends`; constructor injection inside services (services must not import FastAPI).

```
backend/app/{api,core,db,models,schemas,repositories,services,workers,middleware}
backend/{alembic,tests}  frontend/  infra/  docs/  telemetry/
```

## 4. Cross-cutting (build in M1, reuse everywhere)
- **Config:** `pydantic-settings`, all from env, one cached `get_settings()`. For list envs (CORS)
  use `Annotated[list[str], NoDecode]` + a validator that splits on commas (pydantic-settings JSON-
  decodes list fields otherwise).
- **Errors:** typed `AppError` subclasses → central handlers → envelope
  `{"error":{code,message,details,request_id}}`. Never leak stack traces. (FastAPI deprecated
  `ORJSONResponse`; make a tiny custom orjson `Response`.) Use `HTTP_422_UNPROCESSABLE_CONTENT`.
  Sanitize pydantic validation errors (they can embed non-JSON `ctx`).
- **Logging:** structlog; JSON in prod; a pure-ASGI middleware sets `request_id`/`correlation_id` in
  contextvars and logs an access line with latency; echo `X-Request-ID`.
- **DB:** `Base(AsyncAttrs, DeclarativeBase)` with a naming convention; `UUIDPrimaryKeyMixin` +
  `TimestampMixin`; async engine/sessionmaker singletons; `get_session` dependency commits/rolls back.
- **Health:** `/health/live`, `/health/ready` (checks Postgres+Redis), `/metrics` (Prometheus).

## 5. Data model (UUID PKs + created_at/updated_at everywhere)
`users, refresh_tokens, organizations, organization_members, roles, permissions, role_permissions,
apis, api_versions (has upstream_base_url), quotas, rate_limit_rules, api_keys, request_logs,
api_key_usage, audit_logs, telemetry_outbox, daily_usage, notifications`.

## 6. Milestones (each ships migration + tests + docs)
1. **Foundation** — scaffold, config, logging, errors, health/metrics, async DB, Docker/compose, CI,
   Testcontainers harness (function-scoped engine bound to the test's loop; `import app.models` in
   conftest so metadata is populated; truncate between tests).
2. **Auth** — register/login/refresh/logout; **Argon2id**; short JWT access + opaque **refresh token
   stored as SHA-256 hash** with a `family_id`; **rotation with reuse-detection** (replaying a revoked
   token revokes the whole family); email-verify + password-reset via single-use signed action tokens
   (reset bound to a password-hash fingerprint); fixed-window auth throttle in Redis.
3. **Organizations & RBAC** — orgs, members, seeded roles (owner/admin/developer/viewer) +
   permission catalog **in code as source of truth**, seeded idempotently; `require_permission(perm)`
   dependency reading `{org_id}` from path; last-owner protection; **tenant scoping in repositories**.
4. **API management** — register APIs, versions (with `upstream_base_url`), quotas, rate-limit rules;
   ownership validated in the service (an API's `organization_id` must match the path org).
5. **API keys** — generate (shown once; store hash + prefix + last-four), list, revoke (immediate),
   rotate (issue successor + grace-window old).
6. **Rate limiting + Gateway** — Strategy pattern: fixed-window / sliding-window-log / token-bucket,
   each an **atomic Redis Lua** script, keyed per `(api, api_key)`; quota enforcement via Redis
   counters with TTL + rollback. Gateway route `/gw/{api}/{version}/{path:path}` (all methods): auth
   key → resolve api/version+upstream → rate limit → quota → forward via httpx (strip hop-by-hop +
   auth headers) → measure latency/sizes → return upstream response verbatim; unreachable ⇒ 502.
   Tests mock the upstream with respx.
7. **Logging + telemetry outbox** — write `request_logs` + `api_key_usage` upsert + a versioned
   telemetry event **in the same transaction**; `TelemetryEmitter` interface (outbox impl) +
   `TelemetrySink` (logging impl); publisher drains `telemetry_outbox` with `FOR UPDATE SKIP LOCKED`,
   stamps `published_at`. Audit-log security actions (key create/revoke/rotate) the same way.
   **Delivery is at-least-once; consumers dedupe on event_id. No Kafka.** Contract models are
   dependency-light Pydantic in `app/telemetry/events.py` (`request_log`, `audit_log`, schema 1.0).
8. **Analytics** — Celery rollup of `request_logs` into `daily_usage` (idempotent delete-then-
   recompute); summary/error-rate/top-endpoints (p95 via `percentile_cont`) + timeseries queries.
9. **Dashboards + frontend** — developer dashboard endpoint (summary+top endpoints+status breakdown+
   api count) + superuser admin overview; minimal React dashboard (login → org switcher → live stats).
10. **Testing pass** — notifications + request-log structured search; fill coverage.
11. **Deployment + handoff** — Dockerfile (non-root), compose, `.env.example` + `production.env.
    example`, CI; write a handoff summary. **Independently deployable.**

## 7. Key decisions to preserve (the "why")
- Async because I/O-bound (DB+Redis per request, upstream call on gateway).
- Stateless JWT access (no hot-path lookup) + revocable hashed refresh (rotation + reuse detection).
- Fast SHA-256 for API keys (high-entropy) vs slow Argon2 for passwords (low-entropy).
- Lua for rate-limit atomicity (race-free check-and-increment).
- Transactional outbox solves the dual-write problem; at-least-once + dedupe (never claim exactly-once).
- Permission catalog in code (fast checks) + seeded to DB (audit); tenant scoping in repos (defense in depth).

## 8. Gotchas the LLM must handle (learned the hard way)
- asyncpg pools are event-loop-bound → make the test DB engine **function-scoped**; keep containers
  session-scoped.
- Reassigning a lazy relationship in async triggers `MissingGreenlet` → `await obj.awaitable_attrs.x`
  first; base must inherit `AsyncAttrs`.
- `import app.models` in conftest or `create_all` sees empty metadata.
- Postgres has `round(numeric,int)` not `round(double,int)`; don't label a result column `count`
  (clashes with tuple.count).
- Celery beat can't write its schedule file as non-root → `--schedule=/tmp/...`; define `beat_schedule`
  in Celery **config**, not the `on_after_configure` signal (it won't register in the beat process).
- Bleeding-edge FastAPI/Starlette: `include_router` gives lazy objects; `ORJSONResponse` deprecated.

## 9. Testing policy (mandatory, per milestone)
Unit (fakes) + integration/API against **real Postgres + Redis via Testcontainers**; gateway upstream
mocked with respx (no network in CI). Run each milestone's tests and fix before advancing; full suite
at the end; `ruff` + `mypy` clean; every migration `upgrade→downgrade→upgrade` verified on a throwaway
Postgres.

## 10. Definition of done
~90 tests green, ~85% coverage, ruff+mypy clean, `docker compose up` healthy, end-to-end demo:
register→org→API+version(upstream=httpbin)→key→call `/gw/...` until rate-limited/quota-exhausted→
`request_logs` + `daily_usage` reflect it→`telemetry_outbox` fills then drains. Ready for a companion
observability platform (Project B) to consume the telemetry.
