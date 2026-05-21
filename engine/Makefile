.PHONY: up down build test lint fmt check devbox-up devbox-build devbox-shell devbox-down pull-model-host pull-model-local frontend-up frontend-build frontend-down up-shared-ollama

up:
	docker compose up -d

up-shared-ollama:
	docker compose -f docker-compose.yml -f docker-compose.shared-ollama.yml up -d

down:
	docker compose down

build:
	docker compose build

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/
	mypy src/

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

check: lint test

dev:
	uvicorn agent33.main:app --reload --host 0.0.0.0 --port 8000

pull-model-host:
	ollama pull $(MODEL)

pull-model-local:
	docker compose --profile local-ollama up -d ollama
	docker compose exec ollama ollama pull $(MODEL)

devbox-up:
	docker compose --profile dev up -d devbox

devbox-build:
	docker compose --profile dev build devbox

devbox-shell:
	docker compose --profile dev exec devbox bash

devbox-down:
	docker compose --profile dev stop devbox

frontend-up:
	docker compose up -d frontend

frontend-build:
	docker compose build frontend

frontend-down:
	docker compose stop frontend
