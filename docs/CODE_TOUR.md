# Code Tour — Project A

We'll follow **one real request** through every layer of the code, from the URL to the database and
back. By the end you'll know where things live and how the layers connect. Have the repo open; the
`file:line` references are clickable in most editors.

Prereq: skim [CONCEPTS.md](CONCEPTS.md) so the words make sense. Best done with the app **running**
(`docker-compose up` + `python -m scripts.seed_traffic`) so you can hit the endpoint yourself.

---

## The request we'll trace

A program calls a published API through the gateway:

```
GET http://localhost:8000/gw/orders/v1/checkout
Header:  X-API-Key: atp_1234_secret...
```

Goal: authenticate the key, enforce limits, forward to the real "orders" upstream, and record what
happened. Let's watch it.

---

## Hop 0 — the app boots

`backend/app/main.py` builds the FastAPI app: it wires up config, logging, error handling, the
database, and includes all the routers. When uvicorn starts, this is what runs. You don't need to
read it deeply yet — just know it's the "on switch" and the place every router gets registered
(`app/api/router.py`).

---

## Hop 1 — the route (the `api/` layer: the door)

**`app/api/gateway.py` → `proxy(...)`** (around line 31).

This function is the entrypoint for every `/gw/...` call. Notice how **thin** it is — a route's job
is only to translate HTTP into a call to a service:

1. It reads the API key from the headers (`_extract_api_key` — supports `X-API-Key` or
   `Authorization: Bearer`).
2. It packages the incoming HTTP request into a plain object, `IncomingRequest` (method, path, query,
   headers, body, client IP).
3. It calls **one service method**: `await service.handle(incoming, api_key)`. All the real logic is
   in there.
4. It calls `RequestLogService(session).record(outcome)` to persist what happened.
5. It builds the HTTP `Response` to send back (upstream body + status + rate-limit headers).

Where did `service` and `session` come from? They were **injected** — look at the function parameters
`service: GatewayServiceDep, session: SessionDep`. Those are dependencies defined in
`app/api/deps.py`; FastAPI constructs them and hands them in. (That's Dependency Injection from
CONCEPTS.)

> **Layer check:** the route did *no* SQL and made *no* business decisions. It parsed input, called a
> service, serialized output. That's all a route should ever do.

---

## Hop 2 — the service (the `services/` layer: the brain)

**`app/services/gateway.py` → `GatewayService.handle(...)`** (around line 127).

This is where the actual traffic-management rules live, in order:

1. **Authenticate** (`authenticate`, ~line 117) — hash the presented key and look it up:
   `await self.api_keys.get_by_hash(hash_token(presented_key))`. No match → raise
   `AuthenticationError("invalid_api_key")`. Notice it calls a **repository**, never SQL directly.
2. **Resolve the target** — find the API by slug and the *active version* by name
   (`self.versions.get_active(...)`). Unknown version → `404`.
3. **Check the key matches the API** — a key for "orders" can't be used on "payments".
4. **Enforce the rate limit** (`_enforce_rate_limit`, ~line 171) — asks Redis "has this key gone over
   its per-window count?" Over → raise `RateLimitedError` → the caller sees `429`.
5. **Enforce the quota** (`_enforce_quota`, ~line 192) — the longer-term daily/monthly cap (in the DB).
6. **Forward upstream** (`_forward`) — use an HTTP client to actually call the real upstream URL,
   **measuring latency and byte sizes**. If forwarding fails after quota was consumed, it *rolls back*
   the quota (you shouldn't be charged for a request we never served).
7. **Return a `GatewayOutcome`** — a plain data object holding everything that happened: status,
   latency, bytes, the upstream response, rate-limit info. The service hands this back to the route.

> **Layer check:** the service made all the decisions and *orchestrated* repositories + Redis + the
> HTTP client — but it didn't parse HTTP (the route did) and didn't run SQL itself (repositories do).

---

## Hop 3 — the repositories (the `repositories/` layer: the hands)

The service kept calling things like `self.api_keys.get_by_hash(...)` and `self.versions.get_active(...)`.
Those are **repositories** — the only code allowed to touch the database:

- `app/repositories/api_key.py` — look up an API key by its hash.
- `app/repositories/api.py` — find APIs and their versions.
- `app/repositories/telemetry.py` — per-key usage counters + the telemetry outbox.

Open `app/repositories/api_key.py` and find `get_by_hash`. It's a small SQLAlchemy query returning an
`ApiKey` **model** object. That's the boundary: above this line everything is Python objects; below it
is SQL.

---

## Hop 4 — the models (the `models/` layer: the tables)

**`app/models/api_key.py`** defines the `ApiKey` class — each attribute (`key_hash`, `api_id`,
`is_active`…) is a **column** in the `api_keys` table. Same for `app/models/api.py` (APIs + versions),
`app/models/user.py`, `app/models/organization.py`, `app/models/telemetry.py`.

These classes are what migrations (`alembic/`) create as real tables. When the repository returns an
`ApiKey`, you're holding a row from that table as a Python object.

---

## Hop 5 — recording what happened (and the seam to Project B)

Back in the route (Hop 1), after `handle` returned the outcome:

**`app/services/request_log.py` → `record(outcome)`** (around line 24) does three things **in one
database transaction** so they commit together:

1. writes a raw `request_logs` row (the durable record of this call),
2. increments a per-key/day **usage** counter,
3. **emits a telemetry event** (`RequestLogEvent`) into the **outbox**.

That third step is the bridge to Project B. The event's shape is defined in
`app/telemetry/events.py` — a *versioned contract* both projects agree on. The emitter
(`app/services/telemetry/`) later ships outbox rows to a **sink**: by default it just logs them, but
if `TELEMETRY_FORWARD_URL` is set, `HttpForwarderSink` signs them (HMAC) and POSTs them to Project B.

> This is the whole A→B integration in one place: A never calls B during your request. It safely
> stores the fact in its own DB (outbox), and a separate step forwards it. If B is down, your gateway
> call still succeeds.

---

## The round trip, in one glance

```
GET /gw/orders/v1/checkout  (X-API-Key)
   │
   ▼  api/gateway.py  proxy()                 ← parse HTTP, call the service
   ▼  services/gateway.py  handle()           ← auth key → rate limit → quota → forward → measure
   │        ├─ repositories/api_key.py         (find the key)
   │        ├─ repositories/api.py             (find API + version)
   │        ├─ core/redis.py                   (rate-limit counter)
   │        └─ core/http_client.py             (call the real upstream)
   ▼  services/request_log.py  record()       ← save request log + usage + telemetry (one txn)
   │        └─ telemetry/events.py             (the contract) → sink → (optional) Project B
   ▲
   └─ api/gateway.py returns Response          ← upstream body + status + X-RateLimit headers
```

---

## Now you try (small, safe experiments)

1. **Watch a 401.** Call the gateway without a key: `curl localhost:8000/gw/orders/v1/x`. Trace *why*
   you got `missing_api_key` — find where that error string is raised in `services/gateway.py`.
2. **Watch a rate limit.** In the portal, set a tiny rate limit (2/min) on an API, then call it 3
   times fast. Find the code that returns `429` (`_enforce_rate_limit`).
3. **Find the analytics.** The numbers on the dashboard come from `app/services/analytics.py` reading
   `request_logs`. Open it and match a query to a number you see in the UI.
4. **Follow the management side.** Pick *one* portal action (e.g. "create an API key") and trace it
   the same way: `api/api_keys.py` → `services/api_key.py` → `repositories/api_key.py` →
   `models/api_key.py`. You'll see the exact same four-layer shape.

---

## Where to go next

- The **why** behind each choice: [LEARNING_GUIDE.md](LEARNING_GUIDE.md) and
  [architecture.md](architecture.md).
- The **other half**: Project B consumes the telemetry you just saw emitted. Read
  [Project B's START_HERE](../../observability-platform/docs/START_HERE.md), then its
  [CODE_TOUR](../../observability-platform/docs/CODE_TOUR.md) to see your `RequestLogEvent` arrive, get
  stored, and turn into metrics, alerts, incidents, and AI analysis.
