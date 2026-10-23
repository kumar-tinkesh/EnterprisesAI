# ============================================================================
# EnterpriseAI — developer workflow
#
#   make install      # backend deps (uv) + frontend deps (pnpm)
#   make docker-dev   # backend in Docker + web with hot reload (:3001)
#   make test         # backend + frontend tests
# ============================================================================
SHELL := /bin/bash
# pnpm from PATH, else the version web/package.json pins, through npx.
PNPM := $(shell command -v pnpm >/dev/null 2>&1 && echo pnpm || echo "npx --yes pnpm@$$(node -p "require('./web/package.json').packageManager.split('@')[1]")")

.PHONY: help install install-api install-web upgrade downgrade stamp revision \
        seed-admin api web test test-api test-web docker-up docker-dev docker-down clean help

help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: install-api install-web ## Install all dependencies (uv + pnpm)

install-api: ## Backend deps via uv (uses uv.lock)
	uv sync --frozen

install-web: ## Frontend deps via pnpm (uses pnpm-lock.yaml)
	@# Same as web/Dockerfile: pnpm 11 blocks esbuild/sharp's build scripts unless approved.
	$(PNPM) --dir web install --frozen-lockfile --dangerously-allow-all-builds

upgrade: ## Apply DB migrations to head (auto-runs on API start too)
	uv run alembic upgrade head

downgrade: ## Roll back one migration
	uv run alembic downgrade -1

stamp: ## Mark existing DB as head WITHOUT running migrations (legacy create_all DBs)
	uv run alembic stamp head

seed-admin: ## Seed the platform admin: make seed-admin email=a@b.com password=secret
	uv run python scripts/seed_admin.py --email "$(email)" --password "$(password)"

revision: m="change-me"          ## New autogenerate migration: make revision m="add x"
revision:
	uv run alembic revision --autogenerate -m "$(m)"

api: ## Run auth API on :8001 with reload
	uv run uvicorn src.main:app --app-dir apps/auth --reload --port 8001

web: ## Run Next.js on :3000 with reload
	pnpm --dir web dev

test: test-api test-web ## Run every test suite

test-api: ## Backend pytest suite
	uv run pytest -q

test-web: ## Frontend vitest suite
	pnpm --dir web test

docker-up: ## Full stack in Docker (web :3001, auth :8001, backend :8002)
	docker compose up --build -d
	@echo ""
	@echo "=========================================================================="
	@echo "  🚀  EnterpriseAI Web UI:  http://localhost:3001"
	@echo "  🔐  Auth Service Docs:    http://localhost:8001/docs"
	@echo "  ⚡  Backend API Docs:     http://localhost:8002/docs"
	@echo "  🤖  LLM Gateway Docs:     http://localhost:4000/docs"
	@echo "=========================================================================="

# Dev: the Python services run in Docker with hot reload; the web app runs on
# the host (next dev + Turbopack). A bind-mounted `next dev` inside Docker
# Desktop's VM is slow, natively it compiles and hot-reloads fast.
DEV_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.dev.yml
DEV_SERVICES := auth redis backend llm-gateway worker

docker-dev: ## Backend in Docker (hot reload) + web on the host with Turbopack (:3001)
	@# Host deps (glibc SWC); a node_modules installed inside the Alpine image can't run here.
	@ls -d web/node_modules/.pnpm/@next+swc-linux-x64-gnu@* >/dev/null 2>&1 || CI=true $(MAKE) install-web
	-@$(DEV_COMPOSE) rm -sf web urls >/dev/null 2>&1
	$(DEV_COMPOSE) up --build -d $(DEV_SERVICES)
	@echo ""
	@echo "=========================================================================="
	@echo "  🚀  EnterpriseAI Web UI:  http://localhost:3001   (host, Turbopack)"
	@echo "  🔐  Auth Service Docs:    http://localhost:8001/docs"
	@echo "  ⚡  Backend API Docs:     http://localhost:8002/docs"
	@echo "  🤖  LLM Gateway Docs:     http://localhost:4000/docs"
	@echo "  📜  Backend logs:         $(DEV_COMPOSE) logs -f $(DEV_SERVICES)"
	@echo "  ⏹   Stop the containers:  make docker-down   (Ctrl+C stops only the web app)"
	@echo "=========================================================================="
	@echo ""
	cd web && NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1 \
		NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8002/api/v1 \
		NEXT_TELEMETRY_DISABLED=1 \
		./node_modules/.bin/next dev --turbopack -p 3001

urls: ## Show all active service URLs
	@echo ""
	@echo "=========================================================================="
	@echo "  🚀  EnterpriseAI Web UI:  http://localhost:3001"
	@echo "  🔐  Auth Service Docs:    http://localhost:8001/docs"
	@echo "  ⚡  Backend API Docs:     http://localhost:8002/docs"
	@echo "  🤖  LLM Gateway Docs:     http://localhost:4000/docs"
	@echo "=========================================================================="

docker-down: ## Stop containers (data volumes are kept)
	docker compose down

clean: ## Remove local SQLite db and caches
	rm -f auth.db && rm -rf .pytest_cache apps/auth/.pytest_cache