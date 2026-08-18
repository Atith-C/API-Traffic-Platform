# Project A — Interview Cheat-Sheet

One-screen recall for the API Traffic Management Platform. Full version: [interview-guide.html](interview-guide.html) · [HANDOFF.md](HANDOFF.md) · diagram: [architecture.svg](architecture.svg)

## The pitch (say this first)
Lightweight **API gateway + developer portal** (Kong/Tyk/Apigee-lite), async Python **modular monolith**. The interesting parts aren't CRUD — they're the **gateway data-plane** (rate limiting via Redis Lua, quotas, upstream proxying) and the **transactional outbox** (telemetry never lost). Everything else is clean layering around those two.

## Stack
FastAPI · SQLAlchemy 2 (async) · asyncpg · Postgres · Redis · Celery · Alembic · structlog · Docker · Testcontainers · React/Vite frontend. **90 tests, 85% coverage.**

## Architecture
- **Modular monolith**, async (I/O-bound: DB + Redis per request, upstream call on gateway path).
- **Layering (golden rule):** `api → services → repositories → models`. Business logic never in routes; ORM never touched outside a repository. DI at the edge via `Depends`; constructor injection inside services (framework-agnostic → unit-testable).
- **Request lifecycle:** middleware sets `request_id`/`correlation_id` → router → one service → repos → commit at request end → typed `AppError` → consistent JSON envelope.

## Subsystems (mechanism → why)
| Area | Mechanism | Why it's built this way |
|---|---|---|
| **Passwords** | Argon2id, re-hash on param upgrade | Memory-hard, GPU-resistant, OWASP default |
| **Access token** | Stateless JWT (HS256), ~15min | No DB lookup on the hot path |
| **Refresh token** | Opaque random, stored **SHA-256 hash**, ~14d, httpOnly cookie | Revocable; DB leak isn't replayable |
| **Refresh rotation** | Each use rotates; token has a `family_id` | **Reuse of a revoked token → revoke whole family → force re-login** |
| **Verify/reset** | Signed action tokens; reset bound to password-hash fingerprint | Single-use effect without extra storage |
| **RBAC** | Permission catalog in code = source of truth, seeded to DB; `require_permission(perm)` reads `{org_id}` | Fast in-memory checks; DB copy for audit |
| **Multi-tenancy** | Repos scope every query by `organization_id` | Wrong-tenant ID → 404, structurally (defense in depth) |
| **API keys** | `atp_<id>_<secret>`, store **hash only**, shown once; rotate w/ grace window | Fast lookup per request; DB leak yields no usable keys |
| **Gateway** | auth key → resolve api/version+upstream → rate-limit → quota → forward (httpx) → measure → log → return | Real traffic management, not mocked CRUD |
| **Rate limiting** | Fixed / sliding / token-bucket via **atomic Redis Lua**, keyed per (api, key) | Lua = single-threaded atomic → check-and-increment can't race |
| **Quotas** | Redis counter per key/period/bucket, TTL to period end, rollback on upstream fail | Fast enforcement; Postgres = source of truth |
| **Telemetry** | **Transactional outbox**: event row written in same txn as business write; async drain w/ `FOR UPDATE SKIP LOCKED`; versioned contract | Solves dual-write; at-least-once + dedupe on `event_id`; transport-agnostic (no Kafka needed) |
| **Analytics** | Live queries on `request_logs` (p95 via `percentile_cont`); `daily_usage` rollup for time series | CQRS-lite: separate read model; rollup is idempotent (delete-then-recompute) |

## Killer concepts (rehearse these 3)
1. **Transactional outbox** → the **dual-write problem** (DB write + publish can diverge → lost/phantom events). Fix: write the event in the *same DB transaction*; drain async. Delivery is **at-least-once**; consumers dedupe on `event_id`.
2. **Redis Lua atomicity** → rate limiting is a **read-modify-write**; concurrent requests race. Lua runs atomically (single-threaded) → indivisible check-and-increment.
3. **Refresh rotation + reuse detection** → contains a stolen token by killing the whole family.

## Testing
Unit (pure logic, no Docker) + Integration/API against **real Postgres + Redis via Testcontainers**. Gateway's *outbound* upstream mocked with `respx` (no network in CI). Testcontainers > SQLite because the code uses `percentile_cont`, `ON CONFLICT`, JSONB, `SKIP LOCKED`.

## Scaling answers (SDE-2)
- **Horizontal:** API is stateless; shared state in Postgres/Redis. Outbox drain scales via `SKIP LOCKED`. Bottleneck → Postgres.
- **`request_logs` huge →** partition by time, move to ClickHouse/Timescale, dashboards read the rollup. Write path already goes through outbox → new sink, not a rewrite.
- **Redis SPOF →** replicate/cluster; choose **fail-open** for a limiter (serve traffic) + alert.
- **Known gaps:** rejected requests not persisted as logs; quota only in Redis; publisher polls (→ push/stream at scale); rate limit per-key only (add per-API ceiling).

## War stories (for "hard bug")
- **asyncpg "different loop"** → pools are loop-affine; make the test engine function-scoped.
- **MissingGreenlet** → implicit lazy relationship I/O in async; load via `awaitable_attrs` (+`AsyncAttrs`).
- **Empty test schema** → must `import app.models` so tables register on `Base.metadata`.
- **Postgres `round(double,int)` doesn't exist** → round in Python; don't label a column `count` (tuple method clash).
- **Deploy:** README outside Docker context; Celery beat can't write schedule as non-root (`--schedule=/tmp/...`); nginx cached old API IP after partial rebuild.
- **`CORS_ORIGINS` env** → pydantic-settings JSON-decodes list fields; use `NoDecode` + split.

## Commands
```bash
# Full stack
docker-compose -f infra/docker-compose.yml up --build   # API :8000 /docs · dashboard :5173

# Backend dev
cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cp .env.example .env && alembic upgrade head
uvicorn app.main:app --reload

# Tests (needs Docker running; colima start on macOS)
TESTCONTAINERS_RYUK_DISABLED=true pytest        # full suite
pytest -m unit                                   # fast, no Docker
ruff check . && mypy app                          # lint + types
```
