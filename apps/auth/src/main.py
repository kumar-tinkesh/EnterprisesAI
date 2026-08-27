"""FastAPI entry point for the EnterpriseAI Auth Service.

Includes:
- ``/.well-known/jwks.json`` public key publishing (RS256)
- health check
- automatic schema migration on startup (Alembic -> head, any DATABASE_URL)
- CORS middleware reading from the global settings
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.schemas import HealthResponse, JwksResponse
from src.api.v1.router import api_router
from src.config import Settings, get_settings
from src.core.security import get_jwks

settings: Settings = get_settings()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Bring the schema to `head` automatically — works on a fresh clone,
        # an existing database, and after switching DATABASE_URL (e.g. from
        # SQLite to Postgres). Alembic's env.py calls asyncio.run(), so it
        # must not run inside this event loop: use a worker thread.
        try:
            from src.db.migrations import run_migrations

            await asyncio.to_thread(run_migrations)
            print("[auth] database schema is up to date (alembic=head)")
        except Exception as exc:  # pragma: no cover - best-effort on startup
            print(f"[auth] alembic upgrade failed ({exc}); using create_all fallback")
            try:
                from src.db.session import create_db_tables

                await create_db_tables()
            except Exception as exc2:
                print(f"[auth] DB init skipped: {exc2}")
        if settings.SHOW_LOADED_ENV:
            from pprint import pprint

            pprint(settings.redacted_repr())
        yield

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health():
        return HealthResponse(status="ok", service="auth", version="0.1.0")

    @app.get(
        "/.well-known/jwks.json",
        response_model=JwksResponse,
        tags=["jwks"],
        summary="Public JWKS (RS256) key set",
    )
    async def jwks():
        return get_jwks()

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8001, reload=True)
