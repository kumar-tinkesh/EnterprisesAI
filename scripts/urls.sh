#!/usr/bin/env bash
set -e

echo ""
echo "=========================================================================="
echo "  🚀  EnterpriseAI Web UI:  http://localhost:${WEB_PORT:-3001}"
echo "  🔐  Login / Auth UI:      http://localhost:${WEB_PORT:-3001}/auth"
echo "  🛡️  Auth API Docs:        http://localhost:${AUTH_PORT:-8001}/docs"
echo "  ⚡  Backend API Docs:     http://localhost:${BACKEND_PORT:-8002}/docs"
echo "  🤖  LLM Gateway Docs:     http://localhost:${LLM_GATEWAY_PORT:-4000}/docs"
echo "=========================================================================="
echo ""
