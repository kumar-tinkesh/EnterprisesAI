"""Access-filtered MCP Server Catalog endpoints for User domain."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_user
from src.db.session import get_db

from user.api.schemas import CatalogEntry, CatalogResponse
from user.services.catalog_engine import (
    credential_field_names,
    get_authorized_vendor_catalog,
    get_authorized_vendor_catalog_semantic,
    get_user_connected_server_ids,
)

logger = logging.getLogger("user.catalog")

router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse)
async def get_catalog(
    q: str | None = None,
    top_k: int = 5,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Access-filtered catalog. With ``q``, returns semantic-ranked top-K servers."""
    if top_k < 1:
        top_k = 1
    if top_k > 50:
        top_k = 50

    if q and q.strip():
        servers = await get_authorized_vendor_catalog_semantic(
            db, user=user, query=q.strip(), top_k=top_k
        )
    else:
        servers = await get_authorized_vendor_catalog(db, user=user)
    connected_ids = await get_user_connected_server_ids(
        db, server_ids=[s.id for s in servers], user_id=user.id
    )
    entries = [
        CatalogEntry(
            id=s.id,
            name=s.name,
            description=s.description,
            transport=s.transport,
            server_url=s.server_url,
            bound_tools=s.bound_tools,
            auth_type=s.auth_type,
            credential_fields=credential_field_names(s),
            connected=s.id in connected_ids,
        )
        for s in servers
    ]
    return CatalogResponse(servers=entries, count=len(entries))
