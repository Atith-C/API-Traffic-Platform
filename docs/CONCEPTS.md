# Concepts & Vocabulary — Project A

Every technology and term used in Project A, in plain English. For each: **what it is**, an
**everyday analogy**, **why it's here**, its **siblings** (alternatives), and **where** to see it in
the code. Skim it once; come back when a word trips you up.

> This is the *shared foundation* for both projects. Project B's `CONCEPTS.md` only covers the extra
> things B adds (ClickHouse, vectors, LLM, HMAC) and points back here for the basics.

---

## The web basics (if you've only done scripts + SQL)

**HTTP** — the language browsers and servers speak. A **request** ("GET me /orders") gets a
**response** (a status code like `200 OK` or `404 Not Found`, plus a body). Everything here is HTTP.
*Analogy:* ordering at a counter — you ask (request), they hand something back (response).

**REST API** — a style of building HTTP endpoints around "resources" using verbs: `GET` (read),
`POST` (create), `PUT/PATCH` (update), `DELETE` (remove). *Analogy:* CRUD you know from SQL, but over
HTTP. `POST /organizations` = "create an org".

**JSON** — the text format for request/response bodies: `{"name": "Orders"}`. Python dicts ↔ JSON.

**Status codes** — `2xx` success, `4xx` "you did something wrong" (401 unauthorized, 404 not found,
429 too many requests), `5xx` "the server broke". A's gateway passes these through from your upstream.

**Client / server / upstream** — the *client* calls the *server* (Project A). When A forwards your
call onward to the real API, that real API is the *upstream*. A is a middleman = a **reverse proxy**.

---

## The web framework

**FastAPI** — the Python library that turns functions into HTTP endpoints. You write
`async def create_api(...)` and decorate it with `@router.post("/apis")`; FastAPI handles parsing,
validation, and JSON. *Analogy:* Flask/Django if you've seen them, but async-first and typed.
*Siblings:* Flask, Django REST Framework, Starlette. *Where:* every file in `app/api/`.

**uvicorn / ASGI** — the actual web *server* process that runs your FastAPI app and speaks HTTP.
ASGI is the async standard FastAPI is built on. *Analogy:* the engine; FastAPI is the car body.
*Where:* the `uvicorn app.main:app` command in the Dockerfile / compose.

**async / await** — Python's way to handle many requests at once without threads. `await db.fetch()`
means "start this I/O, and while we wait for the DB, go serve other requests." *Why:* a gateway spends
most of its time *waiting* on the network/DB; async lets one process handle thousands of waits.
*Read `await f()` as "call f and wait for the result."* *Siblings:* threads, multiprocessing, gevent.

**Pydantic / schemas** — classes that **validate and shape** data at the edges. A request body is
parsed into a `schema` object; if a field is missing or the wrong type, FastAPI auto-returns a `422`.
*Analogy:* a bouncer checking IDs before anyone gets in. *Where:* `app/schemas/`.

**Dependency Injection (DI)** — instead of a function creating its own database connection, it
*declares* "I need a session" and FastAPI *provides* one. *Analogy:* you order "a coffee"; you don't
build the espresso machine. *Why:* makes code testable (swap the real DB for a fake in tests).
*Where:* `app/api/deps.py` (the `Depends(...)` things).

---

## Data storage

**PostgreSQL (Postgres)** — the SQL database. Stores users, orgs, APIs, keys, request logs. You know
SQL already; here it's reached through an ORM instead of raw queries. *Siblings:* MySQL, SQLite.

**ORM (SQLAlchemy)** — "Object-Relational Mapper": Python classes ↔ database tables. `User` the class
is the `users` table; `user.email` is a column. You write Python; it generates SQL. *Analogy:* a
translator between Python objects and SQL rows. *Siblings:* Django ORM, raw SQL, SQLModel.
*Where:* `app/models/` (the tables) and `app/repositories/` (the queries).

**asyncpg** — the async driver that actually talks to Postgres over the network. You won't touch it
directly; SQLAlchemy uses it. *Analogy:* the phone line to the database.

**Migrations (Alembic)** — versioned, reviewed changes to the database *shape* (add a table, add a
column). Instead of editing the DB by hand, you write a migration file that can be applied
(`upgrade`) or undone (`downgrade`). *Analogy:* git commits, but for your database schema.
*Why:* so every environment (your laptop, production) has the exact same tables. *Where:* `alembic/`.

**Repository pattern** — a class whose only job is DB access for one thing (e.g. `ApiKeyRepository`
has `get_by_hash`). Business code calls the repository, never writes SQL inline. *Why:* one place to
change how data is stored. *Where:* `app/repositories/`.

---

## Speed, background work, and coordination

**Redis** — a very fast in-memory key-value store. Here it does two jobs: **rate limiting** (counting
requests per key per window) and a **cache**. It is *not* the source of truth — if Redis forgets, you
lose a counter, not real data. *Analogy:* a whiteboard for fast scratch notes, vs Postgres = the
filing cabinet. *Siblings:* Memcached. *Where:* `app/core/redis.py`, `app/services/rate_limit/`.

**Rate limiting** — capping how many requests a key may make per time window (e.g. 100/minute); over
the cap → `429 Too Many Requests`. *Why:* protect the upstream from abuse/overload. *Where:*
`app/services/rate_limit/`.

**Quota** — a longer-term cap (e.g. 10,000/day/month) tracked in the DB. Like rate limit but for
billing/fair-use rather than burst protection. *Where:* `app/services/quota.py`.

**Celery + broker** — runs **background jobs** outside the request (so the user isn't kept waiting).
A "broker" (Redis here) is the queue the web process drops jobs into and the "worker" process picks
up. "beat" is a scheduler that enqueues jobs on a timer. *Analogy:* the web process writes a ticket
and moves on; a worker in the back does the slow task. *Siblings:* RQ, Dramatiq, Sidekiq (Ruby).
*Where:* `app/workers/`.

---

## Security

**Authentication vs Authorization** — *authentication* = "who are you?" (log in). *authorization* =
"are you allowed to do this?" (permissions). Different questions; both needed.

**JWT (JSON Web Token)** — a signed token you get after logging in with email+password, then send on
every request (`Authorization: Bearer <jwt>`). It carries your identity and can be *verified* without
a database lookup because it's cryptographically signed. *Analogy:* a tamper-proof wristband from the
entrance — staff can check it without re-checking your ID. *Where:* `app/core/security.py`,
`app/services/auth.py`. **This is how *people* authenticate.**

**API key** — a long random secret (`atp_…`) a *program* sends to use the gateway. Stored **hashed**
(never in plaintext), like a password. *Analogy:* a physical key to one specific door. *Where:*
`app/models/api_key.py`, `app/services/api_key.py`. **This is how *programs* authenticate.**

**Hashing** — a one-way scramble. We store the hash of a key/password; when one is presented we hash
it and compare. Even if the DB leaks, the originals aren't in it. *Siblings:* bcrypt/argon2 (for
passwords), SHA-256 (for high-entropy keys). *Where:* `app/core/security.py`.

**RBAC (Role-Based Access Control)** — permissions grouped into roles (owner/admin/developer/viewer);
a user's role decides what they may do. *Analogy:* job titles with clearance levels. *Where:*
`app/core/permissions.py`.

---

## How A talks to B (the integration seam)

**Telemetry** — structured facts about what happened ("this request took 40ms and returned 200"),
emitted for *another system* (Project B) to analyze. *Where:* `app/telemetry/events.py` defines the
shape (a versioned **contract**).

**Outbox pattern** — instead of calling Project B in the middle of handling a request (slow, and it
might be down), A writes the telemetry into its *own* database in the *same transaction* as the
request log, then a separate step ships it out. *Analogy:* an outbox tray — you drop the letter and
the mail carrier takes it later; if the carrier is out, your letter still safely waits. *Why:* the
user's request never fails just because B is down. *Where:* `app/services/request_log.py`,
`app/services/telemetry/`.

**Sink / forwarder** — the thing that actually *sends* the telemetry. A can log it (default) or
`HttpForwarderSink` it to Project B (signed with HMAC — see B's CONCEPTS). Chosen by an env var.

---

## Running & operating

**Docker** — packages the app + its exact dependencies into an **image** that runs identically
anywhere (a **container** = a running image). *Analogy:* a shipping container — same box on any ship.
*Why:* "works on my machine" stops being a problem. *Where:* `backend/Dockerfile`.

**Docker Compose** — runs *several* containers together (api + db + redis + worker + frontend) with
one command, wired into a private network. *Analogy:* a recipe that starts the whole kitchen.
*Where:* `infra/docker-compose.yml`.

**Environment variables / 12-factor** — configuration (DB URL, secrets) comes from the *environment*,
not hardcoded, so the same image runs in dev and prod with different settings. *Where:*
`app/core/config.py`, `.env.example`.

**structlog** — logging that outputs structured records (with fields like `status`, `latency_ms`)
instead of plain strings, so logs are searchable. *Where:* `app/core/logging.py`.

**Prometheus / metrics** — a `/metrics` endpoint exposing numeric counters a monitoring system can
scrape (request counts, latencies). *Siblings:* StatsD, OpenTelemetry.

---

## Testing

**pytest** — the test runner. Tests live in `backend/tests/`. *Where:* run `pytest`.

**Testcontainers** — spins up a *real* throwaway Postgres/Redis in Docker for the duration of the
tests, so tests run against the real thing, not a fake. *Analogy:* a rehearsal on the real stage.
*Why:* catches bugs a fake DB would hide.

---

Next: [CODE_TOUR.md](CODE_TOUR.md) — watch one request travel through all of this →
