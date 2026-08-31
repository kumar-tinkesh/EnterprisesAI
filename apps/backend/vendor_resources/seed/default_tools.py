"""Default global vendor tools seeded on backend startup (idempotent).

These give solo users a non-empty global catalog out of the box. Seeding is
idempotent: a tool is only inserted if no tool with the same name exists.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vendor_resources.models import VendorTool

logger = logging.getLogger("vendor_resources.seed")

DEFAULT_TOOLS: list[dict] = [
    {
        "name": "notification.sendEmail",
        "description": "Send a transactional email to one or more recipients.",
        "category": "support",
        "method": "POST",
        "endpoint_url": None,
        "parameters_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        "is_global": True,
    },
    {
        "name": "hr.lookupEmployee",
        "description": "Look up an employee record by id or email.",
        "category": "hr",
        "method": "GET",
        "endpoint_url": None,
        "parameters_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "id": {"type": "string"},
            },
        },
        "is_global": True,
    },
    {
        "name": "finance.getInvoice",
        "description": "Retrieve a vendor invoice by id, optionally with line items.",
        "category": "finance",
        "method": "GET",
        "endpoint_url": None,
        "parameters_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string"},
                "include_lines": {"type": "boolean", "default": True},
            },
            "required": ["invoice_id"],
        },
        "is_global": True,
    },
]


async def seed_defaults(db: AsyncSession) -> int:
    """Insert any missing default tools. Returns the number inserted."""
    inserted = 0
    for spec in DEFAULT_TOOLS:
        existing = (
            await db.execute(select(VendorTool).where(VendorTool.name == spec["name"]))
        ).scalars().first()
        if existing is not None:
            continue
        db.add(VendorTool(**spec))
        inserted += 1
    if inserted:
        await db.commit()
        logger.info("Seeded %d default vendor tools", inserted)
    return inserted