# Churn Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Final whole-branch independent review is required.

**Goal:** Reconcile a selected month's fictional churn from the existing MRR bridge to customer and channel/reason CSVs and a readable investigation.

**Architecture:** A packaged module consumes existing marts in one read-only transaction, validates exact Decimal reconciliation and renders deterministic outputs to a new destination. Existing models/report stay unchanged.

**Tech Stack:** Python 3.12, existing DuckDB dependency, standard-library CSV/Decimal/argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-churn-investigation-design.md`

## Global Constraints

- No new dependencies, metric definitions, dbt models, provider calls or contact actions.
- Synthetic data only; historical month-end movements, not current dimension status.
- Native Decimal cents, one read transaction, positive loss inverse of the bridge's signed churn; payment failure is a subset.
- Strict YYYY-MM, existing read-only database and explicitly selected new output directory. No overwrite or validation-error output creation.
- Four deterministic UTF-8 files with no absolute database path or current timestamp.

## Review Focus

- Missing/duplicate customer joins or duplicate bridge rows must fail rather than drop/multiply losses.
- Historical churn must include customers reactivated in a later month; contractions must be excluded.
- A one-cent, customer-count or payment-failure mismatch must be refused without output.
- Empty valid months must remain distinguishable from absent months, with no fabricated percentage.
- Existing directories, symlinks and the input file itself must remain byte-identical on output refusal.

### Task 1: Exact monthly investigation and CLI

**Files:** create `src/saasreport/churn.py`; create `tests/test_churn.py`.

**Interfaces:** `build_investigation(database: Path, month: str, output_dir: Path) -> list[Path]`; CLI `uv run python -m saasreport.churn --database PATH --month YYYY-MM --output-dir NEW_PATH`. Exit 0 success / 2 usage or data error.

- [ ] Write real DuckDB fixture tests for hand-derived amounts, historical state and all review-focus failures; exercise the process CLI.
- [ ] Observe failures because the packaged module is absent; preserve the RED evidence.
- [ ] Implement query/validation, deterministic CSV/Markdown rendering and exclusive-output CLI using existing dependencies.
- [ ] Run targeted tests and resolve genuine failures; run full Python suite, ruff/format and strict mypy. Preserve GREEN evidence.
- [ ] Verify source database bytes do not change, repeated outputs match, and installed-wheel module works outside the checkout.

### Task 2: Reproducible project handoff and reviewed shipping

**Files:** README; new `docs/CHURN_INVESTIGATION.md`; existing `.github/workflows/ci.yml`; optionally tests for real built-warehouse consumer behavior only when needed.

**Interfaces:** consume Task 1 CLI and its exact four-file output; existing CI builds a 24-month seeded warehouse before the module smoke step.

- [ ] Document setup, command, exact outputs, reconciliation/sign/month-end limits and existing-destination refusal. Add a CLI smoke step to existing CI after dbt build; no new service or dependency.
- [ ] Generate a fresh seeded dataset and pass `dbt build`; run the documented month against it and independently compare CSV totals/counts/subset with warehouse SQL.
- [ ] Run required complete checks and inspect diff; commit and request a fresh independent review with exact base/head, spec, relevant verification evidence and failure cases.
- [ ] Fix any blockers test-first, reverify, create/attach PR, inspect exact-head hosted checks through connector, merge only passing reviewed head, then verify main and save a new checkpoint.
