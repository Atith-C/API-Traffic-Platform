"""Seed + continuous traffic generator for Project A (API Gateway) — makes the portal come alive.

Run this against a RUNNING Project A (`docker compose up`). It:
  1. registers a demo user + org and prints the login credentials (to sign into the portal UI),
  2. publishes a few APIs (each pointed at A's own :8000 as a always-reachable upstream, so NO
     internet is needed), with an API key each,
  3. streams randomized gateway traffic through them — a mix of 200s and 404s with real latency —
     which populates A's request logs, analytics, and dashboard.

If Project B is also running and A is configured to forward telemetry, this same traffic flows on to
B as well (see docs/RUNBOOK.md, "Real A→B").

Examples:
    python -m scripts.seed_traffic                 # 2 min of traffic + setup
    python -m scripts.seed_traffic --forever
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
import sys
import time
import uuid

import httpx

# Paths that return 200 when proxied to A itself, plus some that 404 — for a realistic status mix.
GOOD_PATHS = ["health", "openapi.json", "docs", "health/ready", "health/live"]
BAD_PATHS = ["orders/missing", "v2/legacy", "admin/secret", "users/999999", "checkout/expired"]
APIS = ["Orders", "Payments", "Users"]


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def jprint(label: str, value: str) -> None:
    print(f"  {label:16s}: {value}")


def main() -> None:
    p = argparse.ArgumentParser(description="Seed + stream gateway traffic into Project A.")
    p.add_argument("--api", default=env("A_API_BASE", "http://localhost:8000"))
    p.add_argument(
        "--upstream",
        default=env("A_UPSTREAM", "http://localhost:8000"),
        help="Upstream the published APIs proxy to (default: A itself, always reachable)",
    )
    p.add_argument("--duration", type=int, default=120)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--rate", type=float, default=6.0, help="Requests per second")
    args = p.parse_args()

    base = args.api.rstrip("/")
    email = f"demo+{uuid.uuid4().hex[:8]}@acme.io"
    password = "password123"

    with httpx.Client(timeout=15.0) as c:
        try:
            c.get(f"{base}/health").raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"!! Cannot reach Project A at {base} ({exc}).")
            print(
                "   Start it first:  cd ~/Desktop/Work/api-traffic-platform && "
                "docker-compose -f infra/docker-compose.yml up -d"
            )
            sys.exit(1)

        # --- Register + login ---
        c.post(
            f"{base}/auth/register",
            json={"email": email, "password": password, "full_name": "Demo User"},
        )
        login = c.post(f"{base}/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        token = login.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # --- Org + APIs + versions + keys ---
        org = c.post(f"{base}/organizations", json={"name": "Demo Org"}, headers=h).json()["id"]
        published: list[tuple[str, str]] = []  # (slug, api_key)
        for name in APIS:
            api = c.post(f"{base}/organizations/{org}/apis", json={"name": name}, headers=h).json()
            c.post(
                f"{base}/organizations/{org}/apis/{api['id']}/versions",
                json={"version": "v1", "upstream_base_url": args.upstream},
                headers=h,
            )
            key = c.post(
                f"{base}/organizations/{org}/apis/{api['id']}/keys", json={}, headers=h
            ).json()["api_key"]
            published.append((api["slug"], key))

        print("=" * 78)
        print("  PROJECT A — DEMO DATA GENERATOR")
        print("=" * 78)
        jprint("Portal UI", "http://localhost:5173")
        jprint("Login email", email)
        jprint("Login password", password)
        jprint("Organization", org)
        print("  Published APIs (slug → key):")
        for slug, key in published:
            print(f"    - {slug:14s} {key}")
        print("=" * 78)
        print("  Log into the portal with the email/password above to see APIs, keys,")
        print("  request logs, analytics, and the dashboard fill up.")
        print("=" * 78)

        # --- Traffic loop ---
        print("\nStreaming gateway traffic (Ctrl-C to stop)…")
        start = time.time()
        sent = 0
        interval = 1.0 / max(args.rate, 0.1)
        try:
            while args.forever or (time.time() - start) < args.duration:
                slug, key = random.choice(published)
                path = random.choice(GOOD_PATHS if random.random() < 0.8 else BAD_PATHS)
                method = random.choice(["GET", "GET", "GET", "POST"])
                with contextlib.suppress(Exception):
                    c.request(method, f"{base}/gw/{slug}/v1/{path}", headers={"X-API-Key": key})
                sent += 1
                if sent % 50 == 0:
                    print(f"  … {sent} gateway requests sent")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")

    print(f"\nDone — {sent} gateway requests for org {org}.")
    print("Open http://localhost:5173, log in, and explore Dashboard / Analytics / Request Logs.")


if __name__ == "__main__":
    main()
