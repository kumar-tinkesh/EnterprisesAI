#!/bin/sh
# Entrypoint for the EnterpriseAI Auth Service container:
# 1. Check configuration and warn if running without .env
# 2. Apply database migrations (Alembic reads DATABASE_URL from the env).
# 3. Start Uvicorn.
set -e

if [ "$CSRF_SECRET_KEY" = "change-me-in-production" ] || [ -z "$SSO_CLIENT_ID" ]; then
    echo "=========================================================================="
    echo "  [NOTICE] No .env file detected or SSO credentials not configured!"
    echo "  Running with default development settings:"
    echo "    • Database: $(echo "${DATABASE_URL:-sqlite}" | sed "s|://.*||")"
    echo "    • SSO: Disabled / Mock"
    echo "    • CSRF: Using development fallback secret"
    echo ""
    echo "  To configure your custom environment and API keys:"
    echo "    cp .env.example .env"
    echo "=========================================================================="
fi

# A Postgres database (Supabase) must answer before anything starts: when it
# doesn't, say why and stop — never fall back to another database by itself
# (that would split the data in two). backend and worker wait for this one.
case "$DATABASE_URL" in
  postgresql*)
    echo "[entrypoint] checking the database..."
    python - <<'PY' || exit 1
import asyncio, os, re, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

url = os.environ["DATABASE_URL"]

async def main():
    engine = create_async_engine(url, connect_args={"timeout": 10})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    finally:
        await engine.dispose()

try:
    asyncio.run(main())
except Exception as exc:
    host = re.sub(r"^.*@", "", url).split("/")[0].split(":")[0]
    why = (str(exc).splitlines() or [type(exc).__name__])[0].replace(url, "<url>")[:200]
    print("==========================================================================")
    print(f"  [ERROR] Couldn't reach the database ({host}): {why}")
    print("  • A free Supabase project pauses after 7 days unused: restore it in the dashboard.")
    print("  • To work on the local database instead, on the host:  make db-local")
    print("==========================================================================")
    sys.exit(1)
PY
    ;;
esac

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head

echo "=========================================================================="
echo "  🛡️  Auth Service:     http://localhost:${PORT:-8001}"
echo "  📚  Auth Docs:        http://localhost:${PORT:-8001}/docs"
echo "=========================================================================="
exec uvicorn src.main:app \
    --app-dir apps/auth \
    --host 0.0.0.0 \
    --port "${PORT:-8001}" \
    ${UVICORN_EXTRA_ARGS:-}
