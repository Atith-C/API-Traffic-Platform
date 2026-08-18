"""Aggregate API router.

Collects every feature router under a single object mounted by the app factory. Feature routers are
added here as milestones land (auth, organizations, apis, keys, gateway, dashboards, ...).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    analytics,
    api_keys,
    apis,
    audit,
    auth,
    dashboard,
    gateway,
    health,
    metrics,
    notifications,
    organizations,
    request_logs,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(metrics.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(apis.router)
api_router.include_router(api_keys.router)
api_router.include_router(audit.router)
api_router.include_router(analytics.router)
api_router.include_router(dashboard.router)
api_router.include_router(notifications.router)
api_router.include_router(request_logs.router)
api_router.include_router(gateway.router)
