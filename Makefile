# Developer workflow. Every command runs inside the uv-managed virtual environment.

SEED ?= 42
MONTHS ?= 36
SCALE ?= 1.0
RAW_DIR := data/raw
WAREHOUSE := data/warehouse.duckdb

# dbt always runs from the dbt/ directory: profiles.yml lives there and the DuckDB and CSV
# paths in the project are relative to it. Anonymous usage tracking is switched off.
export DBT_PROFILES_DIR := $(CURDIR)/dbt
export DBT_SEND_ANONYMOUS_USAGE_STATS := False

.DEFAULT_GOAL := help
.PHONY: help install data build docs all lint test clean

help: ## List the available targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-9s %s\n", $$1, $$2}'

install: ## Create .venv from uv.lock
	uv sync --locked

data: ## Generate the synthetic raw CSV files in data/raw
	uv run saasgen --seed $(SEED) --months $(MONTHS) --scale $(SCALE) --out $(RAW_DIR)

build: ## Load, transform and test the warehouse (dbt build)
	@test -f $(RAW_DIR)/plans.csv || { echo "No raw data in $(RAW_DIR): run 'make data' first."; exit 1; }
	cd dbt && uv run dbt build

docs: ## Generate the static dbt docs page (dbt/target/static_index.html)
	cd dbt && uv run dbt docs generate --static

all: data build docs ## Run the whole pipeline: data, build, docs

lint: ## Ruff lint, ruff format check and mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test: ## Python tests with coverage
	uv run pytest

clean: ## Delete generated data, the warehouse and dbt artifacts
	rm -rf $(RAW_DIR) $(WAREHOUSE) $(WAREHOUSE).wal dbt/target dbt/logs
