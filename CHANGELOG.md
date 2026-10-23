# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
