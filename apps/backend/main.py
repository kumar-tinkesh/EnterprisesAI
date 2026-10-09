"""FastAPI entrypoint for the EnterpriseAI Backend service.

Responsibilities:
  * Ensure the project root is on ``sys.path`` (absolute imports from any cwd).
  * Register the vendor/user ORM models on the shared ``Base.metadata`` so
    the schema migration / ``create_all`` fallback sees them.
  * Bring the shared database schema to ``head`` (Alembic) on startup, falling
    back to ``create_db_tables()`` if Alembic is unavailable.
  * Mount the vendor and user routers, both under ``/api/v1/vendor/resources``
    (unchanged from before the vendor/user package split — see those routers'
    docstrings for why the prefix stays shared), the knowledge router
    under ``/api/v1/knowledge-bases`` and the builder router under
    ``/api/v1/builder``.

The backend reuses the Auth service's engine/session (``src.db.session``) and
JWT guards (``src.api.deps``) — there is no second engine and no duplicate auth.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── sys.path root injection (before any src.* / vendor.* / user.* imports) ──
ROOT = Path(__file__).resolve().parents[2]  # EnterpriseAI/
for _p in (ROOT, ROOT / "apps" / "auth", ROOT / "apps" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from src.config import get_settings as get_auth_settings  # noqa: E402
from src.db.session import create_db_tables  # noqa: E402

from vendor.api.v1.router import router as vendor_router  # noqa: E402
from user.api.v1.router import router as user_router  # noqa: E402
from knowledge.api.v1.router import router as knowledge_router  # noqa: E402
from builder.api.v1.public import router as public_router  # noqa: E402
from builder.api.v1.router import router as builder_router  # noqa: E402
from builder.services.tool_runtime import shutdown_pool  # noqa: E402

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

    from knowledge.services.ingest import fail_interrupted_documents

    try:
        interrupted = await fail_interrupted_documents()
        if interrupted:
            logger.info("marked %d interrupted knowledge document(s) as failed", interrupted)
    except Exception as exc:  # pragma: no cover - best-effort startup path
        logger.warning("knowledge startup cleanup skipped: %s", exc)

    from vendor.services.embedding import reembed_stale

    async def _reembed():
        try:
            servers, tools = await reembed_stale()
            if servers or tools:
                logger.info("embedded %d MCP server(s) and %d tool(s) for catalog search", servers, tools)
        except Exception as exc:  # pragma: no cover - best-effort startup path
            logger.warning("MCP embedding backfill skipped: %s", exc)

    reembed_task = asyncio.create_task(_reembed())

    from vendor.services.whatsapp_bridge import manager as bridge_manager

    reaper_task = asyncio.create_task(bridge_manager.reaper_loop())

    # Builder runs: with BUILDER_QUEUE_BACKEND=inline this process is also the
    # worker (local dev); with redis, separate `python -m builder.worker`
    # processes run them and this one only enqueues and streams events.
    from builder.config import get_builder_settings
    from builder.runs.events import get_event_bus
    from builder.runs.queue import get_run_queue
    from builder.runs.worker import Worker

    run_worker = None
    if get_builder_settings().BUILDER_QUEUE_BACKEND == "inline":
        run_worker = Worker()
        await run_worker.start()
        with contextlib.suppress(Exception):
            await run_worker.reap()  # resume runs a previous process left behind
    try:
        yield
    finally:
        if run_worker is not None:
            await run_worker.stop()
        await get_run_queue().close()
        await get_event_bus().close()
        reaper_task.cancel()
        reembed_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reaper_task
        # Stop every pooled MCP tool session (and its stdio process).
        await shutdown_pool()
        await bridge_manager.shutdown_all()


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

    # The public API is called from any website (the chat widget) with a
    # publishable key, not a cookie: answer its CORS here, before the
    # credentialed CORSMiddleware above (each key enforces its own origins).
    public_prefix = f"{_backend_settings.BACKEND_API_V1_PREFIX}/public"

    @app.middleware("http")
    async def public_cors(request, call_next):
        if not request.url.path.startswith(public_prefix):
            return await call_next(request)
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
        }
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=headers)
        response = await call_next(request)
        response.headers.update(headers)
        return response

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "service": "backend", "version": "0.1.0"}

    app.include_router(
        vendor_router,
        prefix=f"{_backend_settings.BACKEND_API_V1_PREFIX}/vendor/resources",
        tags=["vendor-resources"],
    )
    app.include_router(
        user_router,
        prefix=f"{_backend_settings.BACKEND_API_V1_PREFIX}/vendor/resources",
        tags=["vendor-resources"],
    )
    app.include_router(
        knowledge_router,
        prefix=f"{_backend_settings.BACKEND_API_V1_PREFIX}/knowledge-bases",
        tags=["knowledge-bases"],
    )
    app.include_router(
        builder_router,
        prefix=f"{_backend_settings.BACKEND_API_V1_PREFIX}/builder",
        tags=["builder"],
    )
    app.include_router(public_router, prefix=public_prefix, tags=["public"])
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("apps.backend.main:app", host="0.0.0.0", port=8002, reload=True)