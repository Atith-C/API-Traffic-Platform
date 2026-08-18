# Gateway Upstreams

The gateway forwards to **configurable real upstream APIs** — the upstream base URL is a property of
each registered API *version* (`api_versions.upstream_base_url`). There is no bundled fake service.
For local development and demos, point a version at one of the stable public APIs below.

## Recommended demo upstreams

### httpbin.org (primary)

- **Base URL:** `https://httpbin.org`
- **Why:** purpose-built HTTP request/response inspection. You can drive status codes, latency, and
  payloads deterministically, which is ideal for exercising the gateway.
- **Auth:** none.
- **Rate limits:** none enforced by the service, but it is a shared community host — be considerate;
  don't run load tests against it.
- **Useful paths (append after `/gw/{api}/{version}/`):**
  - `get`, `post`, `anything` — echoes method, headers, query, and body.
  - `status/{code}` — returns that HTTP status (e.g. `status/503` to test error passthrough).
  - `delay/{seconds}` — delays the response (e.g. `delay/10` to test upstream timeouts).
  - `bytes/{n}` — returns `n` random bytes (test response-size accounting).

### jsonplaceholder.typicode.com (fallback)

- **Base URL:** `https://jsonplaceholder.typicode.com`
- **Why:** stable, read-only REST fixtures (`/posts`, `/users`, ...). Good when httpbin is down.
- **Auth:** none. Writes are faked (200/201 but not persisted).
- **Rate limits:** none documented; again, a shared host — be gentle.

## Limitations & fallback strategy

- Both are third-party and best-effort — **never depend on them in automated tests.** The gateway's
  outbound `httpx` client is injected and replaced with `respx` mocks in the test suite, so CI makes
  **no real network calls** (see `tests/api/test_gateway_api.py`).
- For manual demos, if a public host is slow or unreachable, either switch the version's
  `upstream_base_url` to the other host, or run any local HTTP server and point at
  `http://localhost:<port>`.

## Using an authenticated upstream

If an upstream needs its own credentials (an API key/bearer), the caller supplies them as normal
request headers when calling `/gw/...`; the gateway forwards request headers to the upstream
**except** hop-by-hop headers and the platform's own auth headers (`Authorization`, `X-API-Key`),
which the gateway consumes to authenticate the *consumer*. To inject a fixed upstream credential
transparently, add a per-version header-injection feature later (a natural extension point in
`GatewayService._forward`).
