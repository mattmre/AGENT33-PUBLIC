# AGENT-33 developer Makefile.
# All targets assume you run them from the repo root.

COMPOSE_FILE ?= engine/docker-compose.yml
COMPOSE      ?= docker compose -f $(COMPOSE_FILE)
PYTHON       ?= python
ENGINE_DIR   ?= engine
FRONTEND_DIR ?= frontend

.PHONY: help up down logs ps test lint format typecheck migrate smoke \
        frontend-dev frontend-build frontend-test clean

help: ## Show this help.
	@echo "AGENT-33 make targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Start the full Docker Compose stack in the background.
	$(COMPOSE) up -d --build

down: ## Stop the stack (keeps volumes).
	$(COMPOSE) down

logs: ## Follow logs for the api service.
	$(COMPOSE) logs -f api

ps: ## List compose services.
	$(COMPOSE) ps

test: ## Run the engine pytest suite.
	cd $(ENGINE_DIR) && $(PYTHON) -m pytest tests/ -q

lint: ## Run ruff and mypy on the engine.
	cd $(ENGINE_DIR) && $(PYTHON) -m ruff check src/ tests/
	cd $(ENGINE_DIR) && $(PYTHON) -m mypy src --config-file pyproject.toml

format: ## Auto-fix and format with ruff.
	cd $(ENGINE_DIR) && $(PYTHON) -m ruff check --fix src/ tests/
	cd $(ENGINE_DIR) && $(PYTHON) -m ruff format src/ tests/

typecheck: ## Run mypy in strict mode.
	cd $(ENGINE_DIR) && $(PYTHON) -m mypy src --config-file pyproject.toml

migrate: ## Apply Alembic migrations against the configured DATABASE_URL.
	cd $(ENGINE_DIR) && alembic upgrade head

smoke: ## Run the Docker Compose smoke test.
	bash scripts/docker-smoke-test.sh $(COMPOSE_FILE)

frontend-dev: ## Run the Vite dev server.
	cd $(FRONTEND_DIR) && npm run dev

frontend-build: ## Production build the frontend.
	cd $(FRONTEND_DIR) && npm run build

frontend-test: ## Run the frontend Vitest suite.
	cd $(FRONTEND_DIR) && npm run test

clean: ## Tear down compose with volumes and remove local venv/node_modules.
	-$(COMPOSE) down -v
	rm -rf $(ENGINE_DIR)/.venv
	rm -rf $(FRONTEND_DIR)/node_modules
