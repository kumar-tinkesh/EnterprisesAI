#!/bin/bash
set -e

echo "[backend] Starting EnterpriseAI Backend Service..."

# Run database migrations (shared with auth service)
echo "[backend] Running database migrations..."
alembic upgrade head 2>/dev/null || echo "[backend] Migration skipped (auth service handles it)"

echo "=========================================================================="
echo "  ⚡  Backend API:      http://localhost:8002"
echo "  📚  Backend Docs:     http://localhost:8002/docs"
echo "=========================================================================="
cd apps/backend && exec uvicorn main:app --host 0.0.0.0 --port 8002 ${UVICORN_EXTRA_ARGS:-}
