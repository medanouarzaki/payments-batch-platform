.DEFAULT_GOAL := help

.PHONY: help install requirements lint test up down clean generate inspect

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install all dependencies
	uv sync

requirements:  ## Regenerate requirements.txt from the lockfile
	uv export --format requirements.txt --no-hashes -o requirements.txt

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

generate:  ## Generate and land a daily batch (usage: make generate DATE=YYYY-MM-DD)
ifndef DATE
	$(error DATE is required, usage: make generate DATE=YYYY-MM-DD)
endif
	uv run python -m payments generate --date $(DATE)

inspect:  ## Report the state of a partition (usage: make inspect DATE=YYYY-MM-DD)
ifndef DATE
	$(error DATE is required, usage: make inspect DATE=YYYY-MM-DD)
endif
	uv run python -m payments inspect --date $(DATE)
