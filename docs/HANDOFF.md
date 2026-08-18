# Project A — Handoff

**API Traffic Management Platform** — complete through all 11 milestones. Independently runnable and
deployable. Project B has **not** been started.

## 1. Implementation summary

A production-shaped API Gateway + Developer Portal:

- **Auth** — register/login/refresh/logout, Argon2id hashing, short-lived JWT access + rotating
  refresh tokens with **reuse detection**, email-verify & password-reset via single-use signed
  tokens, brute-force throttle.
- **Organizations & RBAC** — orgs, members, seeded roles (owner/admin/developer/viewer) +
  permission catalog as the single source of truth; `require_permission` dependency; last-owner
  protection; strict multi-tenant scoping.
- **API management** — register APIs, versions (each with an upstream URL), quotas, rate-limit rules.
- **API keys** — issued once (stored as SHA-256 hash), listed, revoked, rotated with a grace window.
- **Gateway** (`/gw/{api}/{version}/{path}`) — authenticates the API key, resolves API+version,
  enforces rate limit + quotas, forwards to the real upstream via httpx, measures latency & sizes,
  records the request, and emits telemetry. **Real traffic management, not mocked CRUD.**
- **Rate limiting** — fixed-window / sliding-window / token-bucket strategies, atomic Redis Lua.
- **Telemetry** — transactional outbox + versioned event contract + async publisher (the Project B
  seam). No Kafka dependency; transport-swappable.
- **Analytics & dashboards** — summary, top endpoints, status breakdown, timeseries (daily rollup),
  top keys; developer dashboard + superuser admin overview.
- **Notifications & search** — in-app notifications; structured request-log search.
- **Frontend** — minimal React + TS + Vite + Tailwind + React Query dashboard.

## 2. Architecture summary

Async modular monolith (FastAPI + SQLAlchemy 2 async + asyncpg), strict layering
`api → services → repositories → models`, business logic never in routes, DI at the edge.
Postgres (data), Redis (rate limit/quota/throttle), Celery (telemetry drain + daily rollup),
structlog + request correlation, Prometheus `/metrics`, OpenTelemetry hooks. Full details and ADRs:
[architecture.md](architecture.md). Telemetry boundary: [telemetry-contract.md](telemetry-contract.md).
Upstream references: [upstreams.md](upstreams.md).

## 3. Test results

- **90 passed**, **0 failed**; **85% line coverage** (business logic — services/repositories/
  telemetry/rate-limit — is the well-covered core). `ruff` clean, `mypy` clean (80 source files).
- Integration/API tests run against **real Postgres + Redis via Testcontainers**; the gateway's
  upstream is mocked with `respx` so **CI makes no real network calls**.
- Every DB migration was verified with an `upgrade → downgrade → upgrade` roundtrip.
- **Live deployment verified**: `docker compose up` → healthy; end-to-end flow against **real
  httpbin.org** (forwarded, measured 1.7s real latency, 503 passthrough); worker drained the
  telemetry outbox; the React dashboard rendered live data through nginx→API.

Run it yourself:
```bash
cd backend && source .venv/bin/activate
TESTCONTAINERS_RYUK_DISABLED=true pytest            # full suite (needs Docker running)
pytest -m unit                                       # fast, no Docker
```

## 4. Known limitations / deliberate scope choices

- **Rejected gateway requests aren't persisted** as `request_logs` (429/401 are visible in access
  logs only); logging the full outcome for rejections is a small extension.
- **Rate-limit scope is per API key** (per-consumer), not per-API-global; both are reasonable — this
  was chosen so one noisy consumer can't starve others.
- **Quota counters live in Redis** (fast enforcement); the authoritative history is `request_logs` /
  `api_key_usage`. A Redis flush resets in-flight quota windows.
- **Add-member requires an already-registered user** (no pending-invite email flow) — keeps scope
  tight; the email-sender abstraction is in place to add it.
- **Telemetry sink is `LoggingSink`** in Project A; Kafka/Redis-Streams sinks are the documented
  extension point (no schema change needed).
- **Frontend is intentionally minimal** (token in localStorage, no router, reload-on-login). It
  proves the API; a production SPA would add silent refresh + routing.
- Coverage of the thin Celery task wrappers (`asyncio.run` shims) is low; their logic
  (`drain_outbox`, `rollup_daily`) is directly tested.

## 5. Setup / run

**Docker (full stack):**
```bash
docker compose -f infra/docker-compose.yml up --build
# API http://localhost:8000  · Docs /docs  · Dashboard http://localhost:5173
```
(This environment uses the standalone `docker-compose` binary; substitute if `docker compose` isn't wired in.)

**Local backend:**
```bash
cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && cp .env.example .env
alembic upgrade head && uvicorn app.main:app --reload
```
Requires a container runtime for tests (Colima on macOS: `colima start`).

## 6. Telemetry contract (for Project B)

Versioned events (`schema_version` 1.0): `request_log`, `audit_log`. Written to `telemetry_outbox`
in the same transaction as the business write; drained async to a swappable sink. Project B can pull
the outbox / raw tables or subscribe to a future stream — **no schema change required**. Pydantic
models in `backend/app/telemetry/events.py`; generated JSON Schemas in `telemetry/schemas/`. Full
detail: [telemetry-contract.md](telemetry-contract.md).

## 7. Recommended end-to-end demo

1. `docker compose -f infra/docker-compose.yml up --build`
2. `POST /auth/register` then `POST /auth/login` → copy `access_token`.
3. `POST /organizations` → create an org.
4. `POST /organizations/{org}/apis` (name "Httpbin"); add version
   `{"version":"v1","upstream_base_url":"https://httpbin.org"}`.
5. Set a rate limit and/or quota on the API; `POST .../keys` → copy the shown-once key.
6. Call the gateway:
   - `GET /gw/httpbin/v1/get?hello=world` with `X-API-Key: <key>` → real httpbin response +
     `X-Gateway-Latency-Ms`.
   - `GET /gw/httpbin/v1/status/503` → upstream status passthrough.
   - Repeat past the limit → `429`.
7. `GET /organizations/{org}/analytics/summary?days=1` and open the dashboard at
   `http://localhost:5173` → live metrics.
8. Inspect `telemetry_outbox` filling then draining (worker) — ready for Project B.

---

**Next step:** awaiting explicit approval before beginning **Project B (Observability & Incident
Intelligence)**, which will consume this telemetry contract.
