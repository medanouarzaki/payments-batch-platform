# dbt needs duckdb 1.5.5 while Airflow ships its own pinned dependency set, so dbt runs in its own venv.
FROM apache/airflow@sha256:aac8468234dfa802c5ac4d6318bbf3b620793b55569ac230f584dc3c1f0ca49d

USER root

RUN python3 -m venv /opt/dbt-venv \
 && /opt/dbt-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/dbt-venv/bin/pip install --no-cache-dir \
      dbt-core==1.12.0 dbt-duckdb==1.10.1 duckdb==1.5.5 \
 && /opt/dbt-venv/bin/pip install --no-cache-dir --only-binary=:all: pyarrow==25.0.0 \
 && /opt/dbt-venv/bin/pip install --no-cache-dir requests python-dotenv pyyaml

USER airflow
