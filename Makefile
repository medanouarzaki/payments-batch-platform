.DEFAULT_GOAL := help

.PHONY: help install lint test up down clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install all dependencies
	uv sync

lint:  ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .

test:  ## Run the test suite
	uv run pytest

up:  ## Start the local stack
	docker compose up -d

down:  ## Stop the local stack and remove volumes
	docker compose down -v

clean:  ## Remove generated data, caches and build artifacts
	rm -rf data/raw data/serving data/warehouse.duckdb
	rm -rf .pytest_cache .ruff_cache dbt/target dbt/logs
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
