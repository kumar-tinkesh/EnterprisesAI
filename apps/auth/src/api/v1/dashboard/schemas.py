"""Schemas for the three role-scoped dashboards."""
from __future__ import annotations

from pydantic import BaseModel


class DashboardResponse(BaseModel):
    dashboard: str
    role: str
    message: str