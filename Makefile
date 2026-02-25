# Makefile for Notex development

.PHONY: help install up down logs restart shell test lint format type-check clean alembic-upgrade alembic-downgrade alembic-revision alembic-current

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies
	pip install -e ".[dev]"
	pre-commit install

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

logs: ## Show logs from all services
	docker compose logs -f

restart: ## Restart all services
	docker compose restart

shell: ## Open a shell in the API container
	docker compose exec api bash

shell-db: ## Open PostgreSQL shell
	docker compose exec db psql -U notex -d notex

test: ## Run tests
	pytest

test-cov: ## Run tests with coverage report
	pytest --cov=app --cov-report=html --cov-report=term

lint: ## Run linter
	ruff check app tests

format: ## Format code
	ruff format app tests
	ruff check --fix app tests

type-check: ## Run type checker
	mypy app

clean: ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov
	rm -rf dist
	rm -rf build

alembic-upgrade: ## Run database migrations
	docker compose exec api alembic upgrade head

alembic-downgrade: ## Rollback one migration
	docker compose exec api alembic downgrade -1

alembic-revision: ## Create a new migration (use msg="description")
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

alembic-current: ## Show current migration version
	docker compose exec api alembic current

dev-setup: ## Set up development environment
	cp .env.example .env
	make install
	make up
	sleep 5
	make alembic-upgrade
	@echo ""
	@echo "Development environment ready!"
	@echo "API: http://localhost:8000"
	@echo "Docs: http://localhost:8000/v1/docs"
