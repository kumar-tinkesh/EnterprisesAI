"""FastAPI entrypoint for the EnterpriseAI Backend service.

Responsibilities:
  * Ensure the project root is on ``sys.path`` (absolute imports from any cwd).
  * Register the vendor_resources ORM models on the shared ``Base.metadata`` so
    the schema migration / ``create_all`` fallback sees them.
  * Bring the shared database schema to ``head`` (Alembic) on startup, falling
    back to ``create_db_tables()`` if Alembic is unavailable.
  * Mount the vendor_resources router under ``/api/v1/vendor/resources``.

The backend reuses the Auth service's engine/session (``src.db.session``) and
JWT guards (``src.api.deps``) — there is no second engine and no duplicate auth.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── sys.path root injection (before any src.* / vendor_resources.* imports) ──
ROOT = Path(__file__).resolve().parents[2]  # EnterpriseAI/
for _p in (ROOT, ROOT / "apps" / "auth", ROOT / "apps" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from src.config import get_settings as get_auth_settings  # noqa: E402
from src.db.session import SessionLocal, create_db_tables  # noqa: E402

# Register vendor_resources models on Base.metadata (side effect of import).
import vendor_resources.models  # noqa: F401,E402
from vendor_resources.router import router as vendor_resources_router  # noqa: E402

from apps.backend.config import get_backend_settings  # noqa: E402

logger = logging.getLogger("backend")

_auth_settings = get_auth_settings()
_backend_settings = get_backend_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Schema: try Alembic (covers auth + vendor tables), else create_all.
    try:
        from src.db.migrations import run_migrations

        await asyncio.to_thread(run_migrations)
        logger.info("database schema is up to date (alembic=head)")
    except Exception as exc:  # pragma: no cover - best-effort startup path
        logger.warning("alembic upgrade failed (%s); using create_all fallback", exc)
        try:
            await create_db_tables()
        except Exception as exc2:  # pragma: no cover
            logger.error("DB init skipped: %s", exc2)

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="EnterpriseAI Backend Service",
        version="0.1.0",
        openapi_url=f"{_backend_settings.BACKEND_API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_backend_settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "service": "backend", "version": "0.1.0"}

    app.include_router(
        vendor_resources_router,
        prefix=f"{_backend_settings.BACKEND_API_V1_PREFIX}/vendor/resources",
        tags=["vendor-resources"],
    )
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("apps.backend.main:app", host="0.0.0.0", port=8002, reload=True)