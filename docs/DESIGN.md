# Design notes

How the warehouse is put together and why. Each decision lists the alternative that was not
chosen, because the trade-off is usually what an interviewer asks about.

## Pipeline at a glance

```
saasgen (Python)         data/raw/*.csv           8 raw tables, money in integer cents
   |
dbt sources              read_csv(..., all_varchar = true), via dbt-duckdb external_location
   |
staging        tables    1:1 with sources: types, names, cleaning, deduplication
intermediate   views     reusable logic: date spine, subscription periods, customer x month spine, funnel
marts/core     tables    star schema: dim_customers, dim_plans, dim_date, fct_mrr, fct_mrr_movements
marts/reporting tables   report-ready aggregates: rpt_mrr_bridge, rpt_cohort_retention, rpt_unit_economics, rpt_funnel
   |
saasreport (Python)      read-only DuckDB queries -> reports/figures/*.png + reports/report.md
```

Everything runs locally from one command (`make all`), in about 8 seconds on a laptop once the
dependencies are installed. CI runs the same steps on a smaller dataset.

## Layers and their contracts

| Layer | Materialisation | Contract |
| --- | --- | --- |
| Sources (`raw`) | external CSV | Exactly what the generator wrote. Every column is text. |
| Staging (`stg_`) | table | One model per source table, no joins. Casts types, renames to conventions, converts cents to dollars, normalises messy values (`utm_source`), removes duplicates (`stg_payments`). |
| Intermediate (`int_`) | view | Business logic that several marts reuse. Not meant for end users. |
| Core marts (`dim_`, `fct_`) | table | Kimball-style dimensions and facts at a stated grain. Explicit column lists. |
| Reporting marts (`rpt_`) | table | Aggregates at the grain a chart or table needs. Explicit column lists. |

The `rpt_` prefix keeps the "every model name starts with its layer" rule while separating
atomic facts (`fct_mrr`, one row per customer-month) from aggregates built on them
(`rpt_mrr_bridge`, one row per month).

## Naming conventions

- Models: `stg_<source table>`, `int_<what it builds>`, `dim_<entity>`, `fct_<process>`,
  `rpt_<report>`. One model per file, CTE-based SQL, lowercase keywords, snake_case.
- Columns: `<entity>_id` for keys, `*_at` for UTC timestamps, `*_date` for dates, `month_start`
  for monthly grain, `*_usd` for money, `*_rate` for ratios between 0 and 1, `is_*` or a verb
  (`started_trial`) for booleans.
- Schemas: `staging`, `intermediate`, `marts`, `seeds`. The `generate_schema_name` macro uses the
  folder's schema name as-is. dbt's default would produce `main_staging` and so on; the default is
  better in a shared warehouse where every developer needs their own prefix.

## Key decisions and trade-offs

**1. MRR comes from subscription events, not invoices.** Invoices answer "what did we bill",
while MRR answers "what is the recurring run-rate". An annual invoice is one large amount once a
year, and an invoice in dunning has not been paid yet. Events are turned into non-overlapping
periods (`int_subscription_periods`), and MRR is read from the period in force at each month end.
Invoices are then used to *test* MRR (`assert_mrr_matches_billing`), which cross-checks two
independent systems. That test caught a real subtlety while the project was being built: after
an involuntary cancellation, the unpaid annual invoice still nominally covers up to a year, so it
overlaps the invoice of a later reactivation. "The invoice in force" therefore has to mean the
most recent invoice covering the day.

**2. Month-end snapshot instead of daily MRR.** One snapshot per customer per month is simple,
standard in SaaS reporting and enough for a monthly bridge. The cost: changes that start and end
within one month are invisible, a subscription that starts on the 30th counts as a full month of
MRR, and one that ends on the 2nd counts as none. A daily grain would be about 30 times larger
and is rarely needed for board metrics.

**3. A gap-free customer x month spine.** `int_customer_months` gives every customer a row for
every month from their first subscription to the end of data, including months after churn.
Without it, `lag(mrr_usd)` would compare non-adjacent months for customers who churn and return,
and the bridge would stop reconciling. The bridge test exists to catch exactly that regression.

**4. Movements are derived from MRR deltas, not event labels.** An `upgrade` event does not
always produce an `expansion` (it might be followed by a failed payment), and a plan change and a
seat change can partly cancel out. Classifying the change in month-end MRR keeps the bridge
consistent with MRR by construction.

**5. Money is `decimal(18, 2)`, rounded once per period.** Floating-point sums of thousands of
values drift by fractions of a cent, and an equality test on a bridge would then fail randomly.
With decimals and a single rounding point (the `monthly_amount` macro), every sum is exact.

**6. Staging is materialised as tables, not views.** The CSV paths in the source definition are
relative to the `dbt/` directory. Views over them would only resolve when queried from that
directory, so the report (which runs from the repo root) could not read them. Tables make the
DuckDB file self-contained and parse each CSV once per build. On a cloud warehouse with real
source tables, staging views would be the usual choice.

**7. Raw data is read as text and typed explicitly in staging.** Letting `read_csv` infer types
would hide problems such as a date column becoming text because of one bad value. Explicit casts
fail loudly instead.

**8. The channel mapping is a seed.** Which `utm_source` belongs to which channel is business
data that marketing can review in a CSV. A `relationships` test from `stg_signups.utm_source` to
the seed fails the build when a new, unmapped source appears.

**9. The price lives on the subscription, not the plan.** Because of grandfathering, two Growth
customers can pay different prices on the same day. Events reference a `plan_price_id`, and
`dim_plans` is really a price book (plan x interval x version).

**10. Unit economics use a trailing 12-month window and first-touch attribution.** That matches
how a finance team reads CAC and payback. The trade-offs, such as spend timing, organic CAC and
constant churn, are listed in [METRICS.md](METRICS.md#unit-economics).

**11. No dbt packages.** The project writes its own `date_spine` macro (DuckDB's
`generate_series`), a `unique_combination_of_columns` test and an `expression_is_true` test,
instead of depending on `dbt_utils`. There is no `dbt deps` step and every line can be explained.
The cost is portability: `dbt_utils.date_spine` works on every warehouse, while this one only
works on DuckDB.

**12. dbt runs from inside `dbt/`.** dbt 1.12 does not change directory for `--project-dir`, so
relative paths in `profiles.yml` and the source definition resolve against the caller's working
directory. The Makefile always `cd`s into `dbt/` and sets `DBT_PROFILES_DIR`, so paths never
depend on where the command is typed. Anonymous usage tracking is disabled both in
`dbt_project.yml` and through an environment variable.

**13. sqlfluff with the Jinja templater.** `make lint` checks every model and singular test
with sqlfluff ([`dbt/.sqlfluff`](../dbt/.sqlfluff)): lowercase keywords, consistent indentation,
explicit join-condition order and explicit columns in tests. The Jinja templater emulates `ref`,
`source` and `var` and loads the project's macros, so linting takes a few seconds and needs no
warehouse. The dbt templater would lint the exact compiled SQL but needs a working dbt
connection, and it is slower and more fragile across dbt versions. Rule ST06 (simple columns
before calculated ones) is disabled because the models order columns by meaning instead.
Satisfying the linter also replaced two multi-line `qualify` clauses with a `row_number()`
column filtered in the next CTE, which is the more portable pattern.

## Testing strategy

| Level | Tool | What it proves |
| --- | --- | --- |
| Generator | pytest (`tests/test_generator.py`) | Same config gives byte-identical files; keys and foreign keys hold; timestamps are ordered (signup <= trial <= conversion; occurred_at <= effective_date); event sequences follow the subscription state machine; invoices match the price book; generated rates land within tolerance of the configured parameters. |
| Source contracts | dbt generic tests on staging | Keys are unique and present, foreign keys resolve, categorical values are in their accepted sets, amounts are non-negative, cancel events and only cancel events have no price. |
| Business invariants | dbt singular tests (`dbt/tests/`) | The bridge reconciles, movements are exclusive and exhaustive, periods never overlap, retention is bounded, MRR is non-negative, billing agrees with MRR, payments agree with invoices, funnels only narrow. |
| Transformation logic | dbt unit tests | Hand-written inputs for `int_subscription_periods` and `fct_mrr_movements` produce the expected rows, including annual normalisation and every movement type. |
| Report | pytest (`tests/test_report.py`) | The report renders from a miniature copy of the marts, is byte-for-byte reproducible and refuses a bridge that does not reconcile. |

Tests are only useful if they can fail, so each one was checked against a deliberate break:

- Changing one expected value in either unit test makes it fail.
- Computing `lag()` over a spine with gaps (dropping zero-MRR months before the window function)
  makes `assert_mrr_bridge_reconciles` fail in 35 of the 36 months.
- Labelling reactivations as `new` makes `assert_mrr_movements_exclusive_and_exhaustive` fail on
  exactly the 94 reactivation rows. The unit test catches the same bug first.

The singular tests restate definitions instead of re-running the model's own SQL. For example,
`assert_mrr_movements_exclusive_and_exhaustive` writes the five movement conditions out again,
so a bug in the model's `case` expression cannot also hide in the test.

## How the synthetic data is made

- One `numpy.random.Generator` per stage, derived with `SeedSequence(seed).spawn()`, so changing
  how billing is simulated does not reshuffle the signups.
- Every parameter (prices, conversion rates, churn by plan and company size, expansion ramp,
  dunning schedule) lives in [`src/saasgen/config.py`](../src/saasgen/config.py). The tests
  compare generated rates with these values.
- Realistic imperfections are added on purpose, so staging has real work to do: hand-typed
  `utm_source` values with odd case and whitespace (3%), duplicate payment webhooks (0.5%), and
  invoices still `open` because their retries fall after the last day of data.
- Plausibility was checked against typical SMB SaaS shapes: about 3% monthly logo churn,
  roughly 70% of a cohort still paying after 12 months, a CAC payback of about 6 to 21 months
  depending on channel, and a visible drop at month 12 when annual contracts come up for renewal.

## Questions to be ready for

- *Why is MRR measured at month end, and what happens to a plan change on the 15th?* The state on
  the last day counts for the whole month; see decision 2.
- *How do you know the MRR bridge is right?* It is an identity (starting + movements = ending)
  enforced by a test every build, and MRR is cross-checked against invoices.
- *What is the difference between churn and contraction, and between new and reactivation?* See
  the movement table in [METRICS.md](METRICS.md#mrr-movements).
- *Why does logo retention never exceed 100% when NRR can?* Logo retention counts a subset of the
  cohort; NRR compares money, and expansion can outgrow losses.
- *How would you make `fct_mrr` incremental?* Rebuild only the months on or after the earliest
  effective date that changed (late-arriving or backdated events), and use
  `is_incremental()` with a delete+insert strategy by month.
- *What breaks on a real warehouse?* `generate_series`, `qualify` and `filter` are not portable
  everywhere; `dbt_utils.date_spine` and `case when` aggregates would replace them.
- *What would you add next?* Snapshots (SCD type 2) of subscription state, proration, multiple
  subscriptions per customer and a semantic layer for metric definitions.
