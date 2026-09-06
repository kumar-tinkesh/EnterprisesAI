# ============================================================================
# EnterpriseAI — developer workflow
#
#   make install      # backend deps (uv) + frontend deps (pnpm)
#   make dev          # run BOTH services with hot reload
#   make test         # backend + frontend tests
# ============================================================================
SHELL := /bin/bash

.PHONY: help install install-api install-web upgrade downgrade stamp revision \
        seed-admin api web dev test test-api test-web docker-up docker-down clean help

help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: install-api install-web ## Install all dependencies (uv + pnpm)

install-api: ## Backend deps via uv (uses uv.lock)
	uv sync --frozen

install-web: ## Frontend deps via pnpm (uses pnpm-lock.yaml)
	pnpm --dir web install --frozen-lockfile

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

dev: ## Run API (:8001) and Web (:3000) together
	$(MAKE) -j2 api web

test: test-api test-web ## Run every test suite

test-api: ## Backend pytest suite
	uv run pytest -q

test-web: ## Frontend vitest suite
	pnpm --dir web test

docker-up: ## Full stack in Docker (web :3000, auth :8001)
	docker compose up --build -d

docker-down: ## Stop containers (data volumes are kept)
	docker compose down

clean: ## Remove local SQLite db and caches
	rm -f auth.db && rm -rf .pytest_cache apps/auth/.pytest_cache