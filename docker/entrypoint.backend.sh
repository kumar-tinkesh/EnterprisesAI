#!/bin/bash
set -e

echo "[backend] Starting EnterpriseAI Backend Service..."

# Run database migrations (shared with auth service)
echo "[backend] Running database migrations..."
uv run alembic upgrade head 2>/dev/null || echo "[backend] Migration skipped (auth service handles it)"

# Start the backend service
echo "[backend] Starting uvicorn server on port 8002..."
cd apps/backend && uv run uvicorn main:app --host 0.0.0.0 --port 8002
