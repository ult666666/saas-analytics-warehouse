# Selected-month churn investigation

The existing report explains aggregate synthetic MRR. A reviewer should also be able to follow one month from the bridge to individual fictional customers, distinguishing voluntary cancellations from payment failures without treating the latter as an additional loss.

The user delegated implementation and shipping choices for comprehensive portfolio depth. This bounded approach is a builder choice grounded in the existing marts, not a claim that the user approved a new analytics product or business conclusion.

## Approach

Keep the tested dbt models and aggregate report unchanged. Add a packaged, read-only consumer at `python -m saasreport.churn` so the workflow works both in the checkout and in an installed distribution. A new dbt mart would duplicate the existing classified movement grain; changing the main report would couple an optional monthly investigation to the existing charts. A separate consumer composes the existing contracts and makes failures inspectable.

Inputs are an existing DuckDB warehouse, strict `YYYY-MM` and a new output directory. Read `marts.rpt_mrr_bridge`, `marts.fct_mrr_movements` and the acquisition channel from `marts.dim_customers` inside one read transaction. Use historical month-end movement state; never use the dimension's latest active status to decide historical churn.

Validate exactly one bridge row for the month, unique churned customer IDs, one matching acquisition record, supported non-null channel/reason, valid zero-ending/positive-prior churn amounts, non-negative bridge loss/count and exact total/count/payment-failure reconciliation. Preserve native Decimal cent amounts; reject floating or sub-cent money instead of rounding mismatches away. The bridge stores churn as negative; exports show the inverse as positive lost MRR. Payment-failure loss is a subset of total churn. A valid no-churn month succeeds with header-only customer/group exports and explicit zero/no-percentage output. Missing/out-of-range months are errors.

Write four deterministic UTF-8 files only after validation: `churned-customers.csv` (all selected-month churn), `payment-failures.csv` (its payment_failed subset), `losses-by-channel-and-reason.csv`, and `investigation.md` with source marts, exact reconciliation, reason/channel totals, subset share and the snapshot caveat. Sort customers by ID and groups by channel/reason. Include no emails, private contact data, source absolute paths, current-time timestamps or proposed customer actions. Every document labels the data fictional and clarifies that month-end snapshots omit within-month cancel/reactivate cycles.

The CLI requires an explicit output directory, refuses any existing destination (including empty directories or symlinks), opens the warehouse read-only and reports usage/data errors with exit 2, success with exit 0. Validation failures produce no report directory. Never replace the aggregate report, warehouse or existing outputs. No new dependency, provider call, deployment service, metric definition or new dbt model.

## Proof

Hand-built real DuckDB fixtures cover exact cents, voluntary/payment-failed mix, contraction exclusion, month isolation, historical customers now active, no churn, bridge mismatches, malformed month, missing/doubled joins, invalid movements/money and output preservation. Real subprocess tests exercise the documented module CLI and installed-package path. Run the full Python/lint/type/SQL suite, a fresh small seeded warehouse through all dbt nodes, the documented command against that warehouse, and an independent review before PR/green-head merge. Keep results synthetic and report methods rather than business outcomes.
