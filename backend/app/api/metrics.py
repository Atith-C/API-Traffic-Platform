"""Prometheus metrics endpoint.

Exposes process + application metrics in the Prometheus text format. This is an observability hook
that Project B (and any Prometheus scraper) can consume without further changes.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
