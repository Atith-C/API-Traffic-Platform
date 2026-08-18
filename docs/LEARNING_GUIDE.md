# Project A — Learning Guide (Backend Interview Syllabus)

Treat this as a syllabus. For every concept: **what** it is, **why** we used it here, and its
**siblings** (the alternatives you'd be asked to compare) with *when you'd pick the sibling instead*.
Companion docs: `interview-guide.html` (visual), `CHEATSHEET.md` (recall), `architecture.svg`.

---

## 0. The one-paragraph mental model
Project A is a **lightweight API gateway + developer portal**. Organizations register APIs, mint API
keys, and route real traffic through a **gateway** that authenticates the key, enforces rate limits +
quotas, forwards to a real upstream, measures it, logs it, and emits telemetry. Everything else
(auth, RBAC, analytics) is clean layering around two hard parts: the **gateway data-plane** and the
**transactional outbox**.

---

## 1. Application shape — "modular monolith"
**What:** one deployable process with strict internal layers (`api → services → repositories →
models`). **Why here:** small cohesive domain; a request's DB writes are one transaction (this is
what makes the outbox trivial); trivial local dev.

**Siblings:**
- **Microservices** — separate deployables per capability. *Pick when:* teams/scale demand
  independent deploy & scale, or capabilities have very different runtime profiles. *Cost:* network
  hops, distributed transactions, ops overhead — overkill here.
- **Layered monolith (no module boundaries)** — *Pick when:* truly tiny app. *Cost:* logic leaks
  into routes, hard to test, hard to split later.
- **Serverless functions** — *Pick when:* spiky, event-driven, stateless. *Cost:* cold starts, awkward
  for a always-warm gateway holding connection pools.

**Interview line:** "Monolith for simplicity + ACID; layered so a module could be extracted later —
services depend on repository interfaces, not each other."

---

## 2. Async everywhere (FastAPI + SQLAlchemy 2 async + asyncpg + httpx)
**What:** non-blocking I/O; one worker handles many concurrent in-flight requests.
**Why here:** the app is **I/O-bound** — every request does DB + Redis round-trips, and the gateway
adds an upstream HTTP call. Async gives gateway-grade concurrency without a thread per request.

**Siblings:**
- **Sync + thread pool (Flask/Django sync, gunicorn threads)** — *Pick when:* CPU-bound work, or a
  team unfamiliar with async. *Cost:* a thread blocked on an upstream call ties up memory; fewer
  concurrent connections.
- **Multiprocessing / worker-per-core** — still used *under* async (uvicorn workers) for CPU parallelism.
- **Goroutines/loom (other langs)** — same goal (cheap concurrency), different runtime.

**Sibling within async:** `asyncpg` (fast native driver) vs `psycopg3` (also async, more general).
We chose asyncpg for speed; the trade-off is asyncpg's stricter type handling.

---

## 3. Layering & Dependency Injection
**What:** routes parse→call one service→serialize; services hold business logic and are
framework-agnostic (no FastAPI imports); repositories are the only layer touching the ORM. Wiring
happens at the edge via FastAPI `Depends`; inside services it's plain constructor injection.
**Why:** testability (swap a fake repo), and a clean seam to extract modules.

**Siblings:**
- **Active Record (Django ORM, Rails)** — models carry persistence + behavior. *Pick when:* CRUD-heavy,
  rapid dev. *Cost:* business logic couples to the ORM; harder to unit-test in isolation.
- **Service locator / global registry** vs **constructor DI** — we use DI; service locator hides
  dependencies and is harder to test.
- **Full DI framework (dependency-injector, Spring)** — *Pick when:* very large graphs. *Cost:* extra
  machinery; FastAPI's `Depends` is enough here.

---

## 4. Auth — password hashing
**What:** **Argon2id** for passwords (memory-hard, GPU-resistant, current OWASP pick). On login we
re-hash if params are outdated; on missing user we still burn a hash to blunt timing attacks.

**Siblings (password hashing):**
- **bcrypt** — battle-tested, but only CPU-hard (weaker vs GPUs), 72-byte input cap. *Pick when:*
  ecosystem constraint.
- **scrypt** — memory-hard like Argon2; Argon2 is the newer standard.
- **PBKDF2** — FIPS-approved, but weakest of these vs modern hardware. *Pick when:* compliance requires it.
- **Plain SHA-256 / MD5** — ❌ never for passwords (too fast → brute-forceable). *We use SHA-256 only
  for high-entropy API keys*, see §7 — different threat model.

---

## 5. Auth — access vs refresh tokens, rotation, reuse detection
**What:** short-lived **JWT access token** (stateless, no DB lookup on the hot path) + long-lived
**opaque refresh token** stored as a **SHA-256 hash**, httpOnly cookie. Every refresh **rotates**
(old revoked, successor issued in the same `family_id`). Replaying a **revoked** refresh token ⇒
theft ⇒ **revoke the whole family** ⇒ force re-login.

**Siblings:**
- **Long-lived stateless JWT only** — *Cost:* can't revoke before expiry; a leak = access until exp.
- **Server-side sessions (opaque session id in Redis/DB)** — *Pick when:* you want central revocation
  and don't need statelessness. *Cost:* a store lookup on every request. (We use stateless access +
  stateful refresh to get both.)
- **Refresh without rotation** — simpler, but a stolen refresh token works silently until expiry.
- **Token binding / DPoP / mTLS-bound tokens** — stronger theft protection; more complex.
- **JWT signing: HS256 (shared secret, what we use) vs RS256/ES256 (asymmetric)** — *Pick RS256 when:*
  multiple services must *verify* without holding the *signing* key (Project B actually validates A's
  HS256 tokens via the shared secret — RS256/JWKS would be the cleaner multi-service choice at scale).

**Verify/reset tokens** are short-lived signed JWTs with a `purpose` claim; reset is bound to a
password-hash fingerprint ⇒ single-use. *Sibling:* store a one-time token row in DB (stateful) — we
chose stateless signed tokens to avoid a table.

---

## 6. RBAC & multi-tenancy
**What:** roles (owner/admin/developer/viewer) → permission sets defined **once in code**
(`core/permissions.py`), seeded to DB for audit; checks use the in-memory map for speed.
`require_permission(perm)` reads `{org_id}` from the path and checks the caller's membership+role.
**Tenant isolation** is enforced in **repositories** (every query filtered by `organization_id`), so a
wrong-tenant id 404s — defense in depth.

**Siblings (authorization models):**
- **RBAC (roles→perms, what we use)** — simple, familiar. *Cost:* coarse; "role explosion" if you need
  fine rules.
- **ABAC (attribute-based)** — decisions from attributes (owner==user, time, IP). *Pick when:* rules
  depend on data, not just role.
- **ReBAC (relationship-based, Google Zanzibar / OpenFGA)** — "user X can view doc Y because in team
  Z". *Pick when:* deep sharing hierarchies (Drive-like).
- **Policy engines (OPA/Rego, Casbin)** — externalize policy. *Pick when:* policies change often /
  must be centralized/audited across services.

**Sibling within RBAC:** enforce-at-gateway vs enforce-in-service vs enforce-in-repo. We do
route + repo (belt and suspenders).

---

## 7. API keys
**What:** `atp_<publicid>_<secret>`; shown **once**; stored as a **SHA-256 hash** (unique-indexed for
O(1) lookup) + prefix + last-four for display. Rotate = issue successor + **grace-window** old; revoke
= immediate.

**Why fast hash here but Argon2 for passwords?** Different threat model: an API key is 256-bit random
(brute-force infeasible) → you want a *fast* deterministic hash you can look up on every gateway
request; a password is low-entropy → needs a *slow* hash.

**Siblings:**
- **Store keys encrypted (reversible)** — *Cost:* you now guard a key; no functional gain (we never
  need to read it back, only recognize it).
- **JWT as API key** — self-describing, no lookup, but can't revoke without a denylist.
- **HMAC request signing (like AWS SigV4)** — key never on the wire; stronger. *Pick when:* MITM risk
  is high. (We *do* use HMAC for the A→B telemetry channel — §12.)
- **mTLS client certs** — strongest machine identity; heavier ops.

---

## 8. The gateway (data-plane) — the centerpiece
**Flow:** auth key → resolve API+version+upstream → **rate limit → quota** → forward via httpx →
measure latency/sizes → record log + usage + telemetry (one txn) → return upstream response.
Header hygiene: strip hop-by-hop + our auth headers. Real 5xx passes through; only *unreachable*
upstream ⇒ synthetic 502.

**Siblings (where do you put a gateway):**
- **Dedicated gateway product (Kong/Envoy/NGINX/Apigee)** — *Pick in prod:* battle-tested, plugins,
  C-speed. We built an app-level gateway to *own* the logic and telemetry (the point of the project).
- **Service mesh sidecar (Istio/Linkerd)** — cross-cutting concerns at the network layer.
- **API composition at the edge (GraphQL gateway/BFF)** — different job (aggregation vs governance).

---

## 9. Rate limiting — the algorithm question
**What:** three strategies (fixed window / sliding-window-log / token bucket), each an **atomic Redis
Lua script**, keyed per `(api, api_key)`. **Lua because** rate limiting is a read-modify-write and
Redis runs a script atomically (single-threaded) → the check-and-increment can't race.

**Siblings (algorithms):**
- **Fixed window** — cheapest; allows 2× burst across a boundary.
- **Sliding window log** — accurate, more memory (a timestamp per request).
- **Sliding window counter** — approximation of the log with two counters; cheaper, slightly less exact.
- **Token bucket** — smooth rate + controlled burst (most flexible).
- **Leaky bucket** — smooths output to a constant rate (shapes traffic); token bucket allows bursts,
  leaky bucket doesn't.

**Siblings (where the atomicity lives):**
- **Lua script (what we use)** vs **Redis transactions (MULTI/EXEC)** vs **WATCH/optimistic** — Lua is
  the cleanest atomic RMW. **Redis functions** (7+) are the newer packaging of Lua.
- **DB-based counters** — too slow/contended for per-request limiting.
- **In-memory per-instance** — breaks across replicas (each node has its own count).

**Fairness sibling:** per-key (we chose — isolates tenants) vs per-API global (protects the upstream).
Real systems layer both.

---

## 10. Quotas
**What:** per-key, per-period (daily/monthly) Redis counters with a TTL to period end; atomic INCR;
rollback on upstream failure. Postgres (`request_logs`/`api_key_usage`) is the source of truth; Redis
is the fast enforcer. **Rate limit = bursts (sec/min); quota = plan volume (month).**

**Siblings:** DB-authoritative quota (accurate, slower), or event-sourced usage metering (Kafka →
aggregate) for billing-grade accuracy.

---

## 11. Telemetry & the transactional outbox — the distributed-systems set-piece
**Problem:** on each request you must write the DB row **and** publish a telemetry event. Two
independent writes = the **dual-write problem** (broker down ⇒ event lost; crash after publish ⇒
phantom event).
**Fix:** write the event into an `telemetry_outbox` table **in the same DB transaction** as the
business write (one ACID commit ⇒ never lost, never phantom). A background publisher drains it
(`FOR UPDATE SKIP LOCKED` so many workers can drain concurrently) and delivers to a swappable
**sink**. Delivery is **at-least-once**; consumers dedupe on `event_id`. Versioned contract
(`schema_version`).

**Siblings:**
- **Change Data Capture (Debezium reading the WAL)** — no app-level outbox table; the DB log *is* the
  event source. *Pick when:* you can run Debezium/Kafka Connect. More infra.
- **Listen/notify (Postgres NOTIFY)** — lighter, but not durable (missed if no listener).
- **Two-phase commit / XA across DB + broker** — the "correct" distributed txn; in practice avoided
  (slow, fragile) — outbox is the pragmatic standard.
- **Direct publish + retries** — simple but has the dual-write hole.

**Exactly-once vs at-least-once:** true end-to-end exactly-once is famously not worth it; **at-least-
once + idempotent consumers (dedupe on id)** is the standard, which is what we do.
**SKIP LOCKED sibling:** advisory locks, or a status column with `SELECT ... FOR UPDATE` (SKIP LOCKED
is the concurrent-safe idiom).

---

## 12. Analytics — read models (light CQRS)
**What:** live queries (summary, top endpoints, p95 via `percentile_cont`) read raw `request_logs`;
long-range **timeseries** reads a pre-aggregated `daily_usage` rollup rebuilt idempotently
(delete-then-recompute).
**Sibling concept — CQRS:** separate the write model (normalized `request_logs`) from read models
(rollups). Full CQRS + event sourcing is the heavier sibling; we use the light version.
**Rollup idempotency sibling:** delete-then-recompute (pure function of source, safe to re-run) vs
incremental upsert (fast but double-counts on re-run).

---

## 13. Cross-cutting
- **Config:** `pydantic-settings`, 12-factor (env-injected, validated once). *Sibling:* a config
  service/Consul (for dynamic config at scale).
- **Errors:** typed `AppError` → one JSON envelope, never leak stack traces (OWASP). *Sibling:* RFC 7807
  "problem+json".
- **Logging:** `structlog` JSON + per-request `request_id`/`correlation_id` in contextvars. *Sibling:*
  OpenTelemetry traces (spans) — we wire OTel hooks for later.
- **Migrations:** Alembic (async), every migration verified `upgrade→downgrade→upgrade`. *Sibling:*
  Django migrations, Flyway/Liquibase (SQL-first).
- **UUID PKs:** non-enumerable, shardable. *Siblings:* auto-increment ints (smaller/faster, but
  guessable/leaky), ULID/UUIDv7 (time-sortable — better index locality than UUIDv4).

---

## 14. Testing
**What:** unit (fakes) + integration/API against **real Postgres + Redis via Testcontainers**; the
gateway's *upstream* is mocked with `respx` (no network in CI). Function-scoped engine (asyncpg
loop-affinity), truncate between tests.
**Why real infra:** the code uses Postgres-specific features (`percentile_cont`, `ON CONFLICT`, JSONB,
`SKIP LOCKED`) — SQLite would pass tests that break in prod.
**Siblings:** in-memory SQLite (fast, wrong dialect), mock-everything (fast, tests the mocks not
reality), full E2E in a staging env (slow, flaky). Testcontainers is the sweet spot.
**Test-double siblings:** *fake* (working impl) vs *mock* (asserts interactions) vs *stub* (canned
answers) vs *spy*.

---

## 15. Deployment
Multi-stage Dockerfile (venv built then copied; **non-root** runtime; healthcheck), docker-compose
(pg/redis/api/worker/beat/frontend), GitHub Actions (ruff + mypy + pytest w/ Testcontainers + image
build). *Sibling:* Kubernetes + Helm (real orchestration), Nomad, ECS.

---

## 16. "How would you scale this?" (senior answers)
- **Stateless API ⇒ N replicas** behind an LB; shared state already in Postgres/Redis. Bottleneck →
  Postgres.
- **`request_logs` huge ⇒** partition by time (drop old partitions cheaply); move to a column store
  (ClickHouse/Timescale — this is literally Project B); dashboards read rollups. The outbox means
  shipping logs elsewhere is a *sink change*, not a rewrite.
- **Redis is a SPOF ⇒** cluster/replicate; choose **fail-open** for a limiter (serve traffic) + alert.
- **Hot partitions / noisy tenant ⇒** per-key limits already isolate; add per-API ceilings.

---

## 17. Rapid sibling cheat-table
| Concept used | Siblings (when you'd pick them) |
|---|---|
| Modular monolith | microservices (scale/teams), serverless (spiky) |
| Argon2id | bcrypt (legacy), scrypt, PBKDF2 (FIPS) |
| Stateless JWT + rotating refresh | server sessions (central revocation), long JWT (simple, risky) |
| HS256 | RS256/ES256 + JWKS (multi-service verify) |
| RBAC | ABAC (data-dependent), ReBAC/Zanzibar (sharing graphs), OPA (central policy) |
| SHA-256 API-key hash | HMAC signing (no key on wire), mTLS |
| Token bucket | leaky bucket (no burst), fixed/sliding window |
| Lua atomicity | MULTI/EXEC, WATCH, Redis functions |
| Transactional outbox | CDC/Debezium, LISTEN/NOTIFY, 2PC |
| At-least-once + dedupe | exactly-once (rarely worth it) |
| Light CQRS rollup | full CQRS+event sourcing |
| Testcontainers | SQLite (wrong dialect), mocks, staging E2E |
| UUIDv4 PK | int (leaky), ULID/UUIDv7 (sortable) |
