# RamCove local development. Everything here is local and simulated; nothing touches a real chain.
SHELL := /bin/bash
export RAMCOVE_ENV ?= demo

.PHONY: help setup db api controller worker web dev seed reset test test-all lint fmt openapi e2e stop

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s $$'\t'

setup: ## install Python and web dependencies
	uv sync
	cd apps/web && npm install

db: ## start PostgreSQL and apply migrations
	docker compose -f infra/docker-compose.yml up -d
	@until docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U ramcove -d ramcove >/dev/null 2>&1; do sleep 1; done
	uv run ramcove-admin migrate

seed: ## seed the labelled demo dataset
	uv run ramcove-admin seed

reset: ## drop, migrate and reseed the demo dataset
	uv run ramcove-admin reset

api: ## run the API on :8787
	uv run ramcove-api

controller: ## run the controller loop
	uv run ramcove-controller

worker: ## run one simulated evaluation worker (w-op-1)
	RAMCOVE_WORKER_ID=w-op-1 RAMCOVE_WORKER_KEY_URI=//RamCoveDemoWorkerOne uv run ramcove-worker

worker2: ## run a second simulated worker (w-op-2)
	RAMCOVE_WORKER_ID=w-op-2 RAMCOVE_WORKER_KEY_URI=//RamCoveDemoWorkerTwo uv run ramcove-worker

web: ## run the web app on :3787
	cd apps/web && npm run dev

dev: ## start everything in the background (logs in var/log)
	@mkdir -p var/log
	@$(MAKE) db
	@$(MAKE) seed || true
	@(uv run ramcove-api > var/log/api.log 2>&1 &) ; sleep 2
	@(uv run ramcove-controller > var/log/controller.log 2>&1 &)
	@(RAMCOVE_WORKER_ID=w-op-1 RAMCOVE_WORKER_KEY_URI=//RamCoveDemoWorkerOne uv run ramcove-worker > var/log/worker1.log 2>&1 &)
	@(RAMCOVE_WORKER_ID=w-op-2 RAMCOVE_WORKER_KEY_URI=//RamCoveDemoWorkerTwo uv run ramcove-worker > var/log/worker2.log 2>&1 &)
	@(cd apps/web && npm run dev > ../../var/log/web.log 2>&1 &)
	@echo "API http://127.0.0.1:8787  ·  Web http://localhost:3787  ·  logs in var/log"

stop: ## stop background development processes
	-pkill -f "ramcove_api|ramcove-api|ramcove_controller|ramcove-controller|ramcove_worker|ramcove-worker" || true
	-pkill -f "next dev -p 3787" || true

openapi: ## export the OpenAPI document and regenerate web types
	uv run ramcove-admin openapi
	cd apps/web && npm run gen:api

test: ## unit tests only (no database required)
	uv run pytest -q tests/unit

test-all: ## unit and database-backed integration tests
	uv run pytest -q tests/unit tests/integration

e2e: ## browser tests against a running stack
	cd apps/web && npx playwright test

lint: ## lint and type-check
	uv run ruff check .
	cd apps/web && npm run lint && npm run typecheck

fmt: ## format
	uv run ruff format packages services miner_cli tests
