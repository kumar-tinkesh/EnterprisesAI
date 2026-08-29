"""Security audit event logging primitives."""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth import AuditEvent


async def log_audit_event(
    db: AsyncSession,
    *,
    action: str,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    resource: str = "",
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditEvent:
    """Record a security or administrative audit event."""
    event = AuditEvent(
        user_id=user_id,
        tenant_id=tenant_id,
        action=action,
        resource=resource,
        detail=detail,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(event)
    await db.flush()
    return event


async def get_audit_events(
    db: AsyncSession,
    *,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Retrieve audit events with optional filtering."""
    query = select(AuditEvent)
    if tenant_id:
        query = query.where(AuditEvent.tenant_id == tenant_id)
    if user_id:
        query = query.where(AuditEvent.user_id == user_id)
    if action:
        query = query.where(AuditEvent.action == action)
    query = query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(query)
    return list(res.scalars().all())
