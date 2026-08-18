# Start Here — Project A (for people new to backend)

Welcome. If you know **Python and SQL** but haven't built web backends before, this is your on-ramp.
Read this page top to bottom once. It tells you *what this project is*, *how the pieces fit*, and
*the exact order to read things* so nothing feels like magic.

There are two sibling projects:
- **Project A (this one)** — an **API Gateway + Developer Portal**.
- **Project B** — an **Observability Platform** that watches traffic and does incident analysis.

They're independent. A works alone; B works alone; A can *optionally* send data to B. Start with A —
it's the simpler mental model.

---

## 1. What is Project A, in one paragraph

Imagine a company that wants to let other developers call its APIs, but safely. Project A is the
**front door and control room** for that. A developer signs up, registers an API (e.g. "Orders API"
that really lives at `https://orders.internal`), and gets an **API key**. When someone calls
`http://our-gateway/gw/orders/v1/checkout` with that key, Project A:

1. checks the key is valid,
2. checks they haven't exceeded their **rate limit** (e.g. 100 requests/minute) or **quota** (e.g.
   10,000/day),
3. **forwards** the call to the real Orders service,
4. measures how long it took and what status came back,
5. **logs** it and produces analytics (request counts, error rates, latency).

That's it. It's a **reverse proxy** (a smart middleman in front of your APIs) plus a **portal** (the
web UI where you manage APIs and keys) plus **analytics**.

Real-world siblings you may have heard of: **Kong, Apigee, AWS API Gateway, Tyk.** This is a compact,
readable version of the same idea.

---

## 2. The big picture

```
                          ┌─────────────────────────────────────────────┐
   A developer's app      │                 PROJECT A                    │
   ───────────────────►   │                                             │
   GET /gw/orders/v1/...   │   Gateway ──► auth key ──► rate limit ──►   │ ──►  the REAL
   header: X-API-Key       │            quota ──► forward ──► measure    │      "Orders" API
                          │                     │                        │      (the upstream)
                          │                     ▼                        │
                          │   log the request + analytics + telemetry   │
                          └──────────────────────┬──────────────────────┘
                                                 │ (optional)
                                                 ▼
                                          Project B (observability)

   Meanwhile, a human uses the PORTAL (web UI) to register APIs, mint keys, and see dashboards.
```

Two kinds of "user" hit Project A, and they authenticate **differently** — remember this, it's the
single most important idea:

| Who | What they do | How they prove who they are |
|---|---|---|
| A **person** (developer) | uses the portal UI / management API | **JWT** (a login token from email+password) |
| A **program** (an app calling your API) | sends traffic through the gateway | **API key** (`X-API-Key: atp_…`) |

---

## 3. The layered architecture (how the code is organized)

Every backend request flows through the same four layers, top to bottom. This is the shape of almost
all professional backends — learn it once here and you'll recognize it everywhere.

```
   HTTP request
        │
        ▼
   api/         ← "routes": receive the HTTP request, validate input, call a service. Thin.
        │
        ▼
   services/    ← the actual business logic ("authenticate the key, then enforce the rate limit…").
        │
        ▼
   repositories/← the ONLY place that talks to the database (reads/writes rows). One job.
        │
        ▼
   models/      ← Python classes that map to database tables (an "ORM").
        │
        ▼
   PostgreSQL / Redis
```

Why bother splitting it? So each layer has **one job** and can be tested and changed on its own. A
route never runs SQL; a repository never makes business decisions. When you read the code, always ask
"which layer am I in?" — it tells you what this file is *allowed* to do.

Folders you'll see under `backend/app/`:
- `api/` routes · `services/` logic · `repositories/` DB access · `models/` tables ·
  `schemas/` request/response shapes (validation) · `core/` config, security, errors, Redis ·
  `db/` database setup + migrations · `telemetry/` the data contract shared with Project B ·
  `workers/` background jobs (Celery) · `middleware/` cross-cutting request handling.

---

## 4. Your reading path (do these in order)

**Step 0 — Run it first.** Reading code you've never seen run is hard. Follow the repo `README.md`
"Quick start" (`docker compose … up`, or `docker-compose` if that errors), then generate data with
`python -m scripts.seed_traffic` and open the portal at http://localhost:5173, logging in with the
email/password it prints. Now you have a live thing to map the code onto.

**Step 1 — Learn the vocabulary.** Open [CONCEPTS.md](CONCEPTS.md). It explains every technology used
here (FastAPI, async, ORM, Redis, JWT, Docker…) in plain English with everyday analogies. Don't
memorize — just skim so the words stop being scary.

**Step 2 — Follow one request through the code.** Open [CODE_TOUR.md](CODE_TOUR.md). It traces a
single gateway call from the URL all the way to the database and back, file by file. This is where
the layers in §3 become real.

**Step 3 — Understand the "why".** Open [LEARNING_GUIDE.md](LEARNING_GUIDE.md) (the interview-style
syllabus: every choice and its alternatives) and [architecture.md](architecture.md). These assume the
vocabulary from Step 1, so do them after.

**Step 4 — See the sibling.** Read Project B's
[START_HERE.md](../../observability-platform/docs/START_HERE.md). A *produces* traffic data; B
*consumes and analyzes* it. Seeing both halves is what makes the whole thing click.

---

## 5. A few honest tips for a beginner

- **You don't need to understand every file.** Understand the *flow* (CODE_TOUR) and the *layers*.
  The rest is detail you can look up.
- **"async" everywhere** just means "this code can pause while waiting for the DB/network and let
  other requests run." Mentally read `await x()` as "call x() and wait for it." That's 90% of it.
- **When lost, find the layer.** `api/` = door, `services/` = brain, `repositories/` = hands that
  touch the DB. That orientation alone answers most "what does this do?" questions.
- Keep the app **running while you read** — change a value, hit the endpoint, watch what happens.

Next: [CONCEPTS.md](CONCEPTS.md) →
