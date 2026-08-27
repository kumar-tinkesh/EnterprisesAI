#!/bin/sh
# Entrypoint for the EnterpriseAI Auth Service container:
# 1. Apply database migrations (Alembic reads DATABASE_URL from the env).
# 2. Start Uvicorn.
set -e

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] starting uvicorn on port ${PORT:-8001}..."
exec uvicorn src.main:app \
    --app-dir apps/auth \
    --host 0.0.0.0 \
    --port "${PORT:-8001}"