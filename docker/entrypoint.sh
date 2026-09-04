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
    echo "    • Database: SQLite (/data/auth.db)"
    echo "    • SSO: Disabled / Mock"
    echo "    • CSRF: Using development fallback secret"
    echo ""
    echo "  To configure your custom environment and API keys:"
    echo "    cp .env.example .env"
    echo "=========================================================================="
fi

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] starting uvicorn on port ${PORT:-8001}..."
exec uvicorn src.main:app \
    --app-dir apps/auth \
    --host 0.0.0.0 \
    --port "${PORT:-8001}"
