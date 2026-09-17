# ROOM local development. Everything here is local and simulated; nothing touches a real chain.
SHELL := /bin/bash
export ROOM_ENV ?= demo

.PHONY: help setup db api controller worker web dev seed reset test test-all lint fmt openapi e2e stop

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s $$'\t'

setup: ## install Python and web dependencies
	uv sync
	cd apps/web && npm install

db: ## start PostgreSQL and apply migrations
	docker compose -f infra/docker-compose.yml up -d
	@until docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U room -d room >/dev/null 2>&1; do sleep 1; done
	uv run room-admin migrate

seed: ## seed the labelled demo dataset
	uv run room-admin seed

reset: ## drop, migrate and reseed the demo dataset
	uv run room-admin reset

api: ## run the API on :8787
	uv run room-api

controller: ## run the controller loop
	uv run room-controller

worker: ## run one simulated evaluation worker (w-op-1)
	ROOM_WORKER_ID=w-op-1 ROOM_WORKER_KEY_URI=//RoomDemoWorkerOne uv run room-worker

worker2: ## run a second simulated worker (w-op-2)
	ROOM_WORKER_ID=w-op-2 ROOM_WORKER_KEY_URI=//RoomDemoWorkerTwo uv run room-worker

web: ## run the web app on :3787
	cd apps/web && npm run dev

dev: ## start everything in the background (logs in var/log)
	@mkdir -p var/log
	@$(MAKE) db
	@$(MAKE) seed || true
	@(uv run room-api > var/log/api.log 2>&1 &) ; sleep 2
	@(uv run room-controller > var/log/controller.log 2>&1 &)
	@(ROOM_WORKER_ID=w-op-1 ROOM_WORKER_KEY_URI=//RoomDemoWorkerOne uv run room-worker > var/log/worker1.log 2>&1 &)
	@(ROOM_WORKER_ID=w-op-2 ROOM_WORKER_KEY_URI=//RoomDemoWorkerTwo uv run room-worker > var/log/worker2.log 2>&1 &)
	@(cd apps/web && npm run dev > ../../var/log/web.log 2>&1 &)
	@echo "API http://127.0.0.1:8787  ·  Web http://localhost:3787  ·  logs in var/log"

stop: ## stop background development processes
	-pkill -f "room_api|room-api|room_controller|room-controller|room_worker|room-worker" || true
	-pkill -f "next dev -p 3787" || true

openapi: ## export the OpenAPI document and regenerate web types
	uv run room-admin openapi
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
