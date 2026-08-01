.DEFAULT_GOAL := help

.PHONY: help install requirements lint lint-ci lint-sql test dbt-full-build up down clean generate inspect fetch-fx export-marts dashboard-install dashboard dashboard-test dbt-debug dbt-seed dbt-test dbt-run dbt-build init-env backfill

DBT_ENV = PAYMENTS_WAREHOUSE_PATH="$$(uv run python -c 'from payments.config import get_settings; print(get_settings().warehouse_path)')" \
	PAYMENTS_RAW_TRANSACTIONS_DIR="$$(uv run python -c 'from payments.config import get_settings; print(get_settings().raw_transactions_dir)')" \
	DBT_PROFILES_DIR="$(CURDIR)/dbt"

help:  ## Show this help
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install all dependencies
	uv sync

requirements:  ## Regenerate requirements.txt from the lockfile
	uv export --format requirements.txt --no-hashes -o requirements.txt

lint:  ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .

# an untracked directory at the repo root can change ruff's import
# classification, making local lint more permissive than CI's clean checkout
lint-ci:  ## Lint a copy of the tracked and untracked-but-not-ignored files only
	@tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT INT TERM; \
	git ls-files --cached --others --exclude-standard -z | tar --null -T - -cf - | tar -xf - -C "$$tmp"; \
	status=0; \
	"$(CURDIR)/.venv/bin/ruff" check --no-cache "$$tmp" || status=$$?; \
	"$(CURDIR)/.venv/bin/ruff" format --check --no-cache "$$tmp" || status=$$?; \
	exit $$status

lint-sql:  ## Lint the dbt models with sqlfluff
	uv run sqlfluff lint dbt/models

test:  ## Run the test suite
	uv run pytest --cov=payments --cov-report=term-missing

dbt-full-build:  ## Build the whole dbt project once and check every test runs
	uv run pytest tests/integration/test_full_dbt_build.py -v -s

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

fetch-fx:  ## Cache-first fetch of exchange rates (usage: make fetch-fx DATE=YYYY-MM-DD)
ifndef DATE
	$(error DATE is required, usage: make fetch-fx DATE=YYYY-MM-DD)
endif
	uv run python -m payments fetch-fx --date $(DATE)

export-marts:  ## Publish warehouse marts to a separate serving file
	uv run python -m payments export-marts

dashboard-install:  ## Create the dashboard virtualenv from its pinned requirements
	uv venv .venv-dashboard --python 3.11
	uv pip install --python .venv-dashboard/bin/python -r dashboard/requirements.txt

dashboard:  ## Run the dashboard on port 8501 against the serving file
	.venv-dashboard/bin/streamlit run dashboard/app.py \
		--server.port 8501 --server.address 0.0.0.0 \
		-- --serving-path "$$(uv run python -c 'from payments.config import get_settings; print(get_settings().serving_dir / "marts.duckdb")')"

dashboard-test:  ## Run the dashboard test suite in its isolated environment
	.venv-dashboard/bin/python -m pytest dashboard/tests

dbt-debug:  ## Check the dbt profile can connect to the warehouse
	$(DBT_ENV) uv run dbt debug --project-dir dbt

dbt-seed:  ## Load reference seeds into the warehouse
	$(DBT_ENV) uv run dbt seed --project-dir dbt

dbt-test:  ## Run dbt tests
	$(DBT_ENV) uv run dbt test --project-dir dbt

dbt-run:  ## Run dbt models
	$(DBT_ENV) uv run dbt run --project-dir dbt

dbt-build:  ## Seed, run and test the dbt project
	$(DBT_ENV) uv run dbt build --project-dir dbt

init-env:  ## Generate a local .env with random Postgres and Airflow secrets
	@if [ -f .env ]; then \
		echo ".env already exists; remove it by hand before regenerating secrets" >&2; \
		exit 1; \
	fi
	@AIRFLOW_UID=$$(id -u) uv run python -c "import os, secrets, base64; lines = ['POSTGRES_DB=airflow', 'POSTGRES_USER=airflow', f'POSTGRES_PASSWORD={secrets.token_urlsafe(24)}', f'AIRFLOW_FERNET_KEY={base64.urlsafe_b64encode(os.urandom(32)).decode()}', 'AIRFLOW_ADMIN_USER=airflow', f'AIRFLOW_ADMIN_PASSWORD={secrets.token_urlsafe(24)}', f'AIRFLOW_UID={os.environ[\"AIRFLOW_UID\"]}']; open('.env', 'w').write('\n'.join(lines) + '\n')"

backfill:  ## Backfill payments_daily for a date range (usage: make backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD [DRY_RUN=1] [RESET=1])
ifndef FROM
	$(error FROM is required, usage: make backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD)
endif
ifndef TO
	$(error TO is required, usage: make backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD)
endif
	docker compose exec -T airflow-scheduler airflow dags backfill payments_daily \
		--start-date $(FROM) --end-date $(TO) $(if $(DRY_RUN),--dry-run,) $(if $(RESET),--reset-dagruns -y,)
