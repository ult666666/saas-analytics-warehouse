# From the MRR bridge to fictional customer records

The aggregate report explains how MRR changed. This optional consumer traces one historical
month's churn to the customers and acquisition channels behind the same numbers. Payment-failure
churn remains a subset of total churn throughout the investigation.

All records describe Tallyloom, the project's fictional SaaS company. They show a reproducible
analytics method, not customer behavior observed in a real business.

## Run the complete workflow

From a fresh checkout with uv and make installed:

```bash
uv sync --locked
make data build MONTHS=24 SCALE=0.25
uv run python -m saasreport.churn \
  --database data/warehouse.duckdb \
  --month 2024-12 \
  --output-dir build/churn-2024-12
```

Choose a **new** output directory on each run; even an existing empty directory is refused.
The consumer never replaces the warehouse, the aggregate report or existing investigations.
Choose a month actually present in `marts.rpt_mrr_bridge`. The default 36-month build covers
January 2023 through December 2025. A valid month without churn produces a successful zero
investigation; a month absent from the bridge is an error.

The module also ships in the Python wheel and runs as `python -m saasreport.churn` after installation.
No extra service, credentials or network access is needed to query an already built warehouse.

## Inspect the outputs

| File | Grain and purpose |
| --- | --- |
| `investigation.md` | Readable reconciliation, loss/subset share, channel/reason table, source marts and interpretation limits. |
| `churned-customers.csv` | One row per customer whose month-end MRR went from positive to zero in the selected month. |
| `payment-failures.csv` | Only the `payment_failed` rows from the first file; not an additional set of losses. |
| `losses-by-channel-and-reason.csv` | One row per observed acquisition-channel and cancellation-reason pair, with customer count and total lost MRR. |

CSV amounts are positive USD losses with exactly two decimal places. For example, a bridge
movement of `-101.25` becomes `101.25` lost MRR. No total rows are mixed into customer/group
exports. An empty successful export still has its header. The Markdown report uses `n/a` for
the payment-failure share when there is no churned MRR.

Customer IDs are fictional. The exports contain no names, addresses or contact instructions.
The output is deterministic for the same selected source state: stable order, no timestamp or
absolute database path. Generating the same month in two new destinations yields identical bytes.

## Reconciliation and refusal cases

The consumer opens DuckDB read-only and reads these marts in one transaction:

1. `marts.rpt_mrr_bridge`: selected-month signed total churn, signed involuntary churn and count.
2. `marts.fct_mrr_movements`: only that month's `movement_type = 'churn'` records, including the
   previous/current MRR and classified reason.
3. `marts.dim_customers`: first-touch acquisition channel joined by customer ID.

Native Decimal amounts are converted to exact integer cents. The consumer refuses floating-point
or sub-cent money instead of rounding inconsistencies away. It checks that each churn row moves
positive previous MRR to zero, with the corresponding exact negative change. It then requires:

```text
number of exported customers = bridge.churned_customers
sum(customer lost MRR)        = -bridge.churned_mrr_usd
sum(payment_failed lost MRR)  = -bridge.involuntary_churned_mrr_usd
```

Duplicate bridge rows, duplicate movement/customer joins, missing customer/channel/reason,
unsupported channel/reason and any count or cent mismatch stop the investigation before a report
directory is created. This complements the existing dbt tests; it does not replace `dbt build`
or audit unrelated warehouse rows. CLI success returns `0`; invalid input, source inconsistencies
or output refusal return `2` with a diagnostic. A filesystem failure while writing cleans up
the files that this invocation created; it never removes a pre-existing report.

## What the investigation means

MRR is measured at month end. A customer who cancels and returns within the same month with
unchanged MRR does not appear here. A customer who churned in the selected month and reactivated
later still appears; the current dimension's active flag does not rewrite historical state.
The reason comes from the cancellation event already classified by the mart. `payment_failed`
does not mean every failed charge, outstanding invoice or cash recovery opportunity. Acquisition
channel is first-touch attribution, not the cause of churn.

These are descriptive fictional losses, with no recovery estimate, causal effect, customer
contact action or market benchmark. The existing aggregate charts and metric definitions stay
unchanged.

## Verification

```bash
uv run pytest tests/test_churn.py -q --no-cov
make test
make lint
```

The tests use real small DuckDB marts with hand-derived cent totals, a now-active historical
customer, a contraction that must be excluded, a different month's loss, a no-churn month,
deliberate count/cent/subset mismatches, broken joins, invalid dates and preserved existing
destinations. A real process runs the documented module. CI additionally builds a fresh
24-month synthetic warehouse and consumes its December 2024 bridge with this command.
