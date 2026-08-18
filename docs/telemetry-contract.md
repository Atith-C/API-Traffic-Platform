# Telemetry Contract (Project A → Project B)

Project A emits **versioned telemetry events** that the Observability platform (Project B) ingests.
This contract is deliberately decoupled from Project A's transactional tables so that B can consume
it **without any schema change** to Project A.

## Source of truth

- Pydantic models: [`backend/app/telemetry/events.py`](../backend/app/telemetry/events.py)
- Generated JSON Schemas: [`telemetry/schemas/`](../telemetry/schemas/)
- Current `schema_version`: **1.0**

Every event shares an envelope:

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | string | Bumped on breaking changes; consumers branch on it. |
| `event_type` | string | `request_log` \| `audit_log`. |
| `event_id` | uuid | Unique per event (idempotency key for consumers). |
| `occurred_at` | datetime (ISO-8601) | When the event happened. |

### `request_log` (primary signal)

Adds: `organization_id`, `api_id`, `api_version_id`, `api_key_id?`, `method`, `path`,
`status_code`, `latency_ms`, `request_bytes`, `response_bytes`, `client_ip`, `upstream_url`.

### `audit_log`

Adds: `organization_id?`, `actor_user_id?`, `action`, `resource_type`, `resource_id?`, `ip?`,
`metadata` (object).

## Delivery — transactional outbox

1. When Project A serves a gateway request (or performs an audited action), it writes the business
   row **and** an outbox row (`telemetry_outbox`) **in the same database transaction**. An event is
   therefore never lost and never duplicated at the source.
2. A background publisher drains pending outbox rows (`published_at IS NULL`) using
   `FOR UPDATE SKIP LOCKED` (safe for concurrent workers), delivers them to a **sink**, and stamps
   `published_at`.
3. The default sink logs structured events. Because delivery is behind the `TelemetrySink` /
   `TelemetryEmitter` interfaces, a **Kafka** or **Redis Streams** sink can be added later with **no
   change to the event schema, the outbox, or any business code**.

```
business write ─┐
                ├─ (same txn) ─▶ telemetry_outbox ──(publisher)──▶ sink ──▶ Project B
outbox write ───┘                                   drain + mark published
```

## How Project B consumes it

Two supported paths, both zero-schema-change:

- **Pull the outbox / raw tables**: read `telemetry_outbox` (or `request_logs` / `audit_logs`)
  directly on a schedule. Rows remain after publishing (only `published_at` is set), so history is
  preserved.
- **Subscribe to a stream**: once a Kafka/Redis-Streams sink is configured in Project A, B consumes
  the stream. The payloads are byte-for-byte the same as the JSON Schemas here.

## Versioning policy

- Additive, optional fields → **no** version bump.
- Removing/renaming a field or changing a type → bump `schema_version`; publish both versions during
  a migration window if needed. Consumers must tolerate unknown fields.
