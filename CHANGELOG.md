# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Incremental staging: `stg_signups`, `stg_trials`, `stg_subscription_events`, `stg_invoices`,
  `stg_payments` and `stg_marketing_spend` are incremental models (`delete+insert` on their
  unique key) that reprocess an `incremental_lookback_days` window (7 days), so late rows are
  absorbed and newer versions replace older ones.
- `snp_subscription_state`, a dbt snapshot (SCD type 2, timestamp strategy on business dates)
  of each customer's plan, seats, price, MRR and status, built from the new
  `int_subscription_state` model, with four singular tests and a unit test.
- `saasgen --daily-batches DIR` writes the same seeded data as daily batches, including
  invoices that arrive again when their status changes and a seeded 3% of the rows that can be
  late (all but payments, plans and marketing spend) arriving one to five days late.
- `python -m saasgen.backfill` (`make incremental-check`): loads the batches day by day, builds
  incrementally with snapshots, runs every test and compares every relation with a full
  refresh row by row. CI runs a short version.

### Changed

- Raw invoices have an `updated_at` column (when the status last changed); `stg_invoices`
  keeps the newest version of each invoice. Every other generated value is unchanged, and
  `reports/report.md` is identical.
- `make data` deletes the warehouse file, since incremental tables and the snapshot keep state
  that belongs to one dataset. A warehouse built by an earlier version needs `make clean` (or
  `dbt build --full-refresh`) once.
- `SAAS_WAREHOUSE` and `SAAS_RAW_DIR` can point dbt at another DuckDB file and raw folder.

## [0.1.0] - 2026-10-23

### Added

- `saasgen`: a seeded, deterministic generator of synthetic raw data for Tallyloom, a fictional
  B2B SaaS company. It writes plans, marketing spend, signups, trials, customers, subscription
  events, invoices and payments as CSV, with a CLI and pytest coverage for determinism,
  integrity, ordering and calibration.
- dbt project on DuckDB: 8 staging, 4 intermediate and 9 mart models (MRR, MRR movements, MRR
  bridge, cohort retention, unit economics, funnel), 149 data tests including 8 singular
  business-invariant tests, and 2 unit tests.
- `saasreport`: charts and a markdown report generated from the marts.
- Makefile workflow (`make all`, `make lint`, `make test`, ...), sqlfluff linting of the dbt
  SQL, a CI workflow and a GitHub Pages workflow for the static dbt docs.
- Documentation: README, metric definitions (`docs/METRICS.md`) and design notes
  (`docs/DESIGN.md`).
