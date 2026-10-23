# Metric definitions

Every metric in the marts, with its formula, grain and edge cases. Model and column names refer
to the dbt project in [`dbt/`](../dbt). All data is synthetic (Tallyloom is a fictional company).

## Conventions

- **Money** is US dollars with two decimals (`decimal(18, 2)`). The raw files store integer
  cents; `cents_to_dollars` converts them in staging. Sums of decimals are exact, which is why the
  MRR bridge can be tested for equality to the cent.
- **Time** is UTC. Metrics use **effective dates** (when a change takes effect), never the
  timestamp at which a change was requested (`occurred_at`).
- **Calendar.** The reporting calendar (`int_date_spine`, `dim_date`) runs from the first to the
  last day of data. The generator writes marketing spend for every day of the simulated window,
  so the spend dates define it. Months are calendar months.
- **Rates** are stored as ratios between 0 and 1 (`0.0299` = 2.99%). Rates over several months
  are pooled, as a ratio of sums, never an average of monthly percentages.

## The business being measured

The marts make the most sense with Tallyloom's (fictional) billing rules in mind. They live in
[`src/saasgen/lifecycle.py`](../src/saasgen/lifecycle.py):

- Three seat-based plans (Starter, Growth, Enterprise), billed monthly or annually. Annual
  billing costs 12 x the monthly list price x 0.8 (a 20% discount).
- **One list-price change** halfway through the data. New subscriptions, plan changes and
  reactivations get the new price; existing subscriptions keep their price (grandfathering),
  including when they add or remove seats.
- A subscription renews on the anniversary of its start date. Plan and seat changes requested
  during a period take effect at the next renewal, so there is no proration.
- Voluntary cancellations take effect at the end of the paid period.
- A failed renewal charge is retried 3, 7 and 14 days after the invoice date. If every retry
  fails, the invoice becomes `uncollectible` and the subscription is cancelled on the day of the
  last retry (`cancel_reason = 'payment_failed'`, i.e. involuntary churn).
- The first invoice of a new or reactivated subscription is always paid: a declined checkout never
  becomes a subscription.

## MRR (monthly recurring revenue)

**Model:** `fct_mrr`. **Grain:** customer x calendar month.

```
MRR(customer, month) = seats x unit_amount_usd / k
    k = 1 for monthly prices, 12 for annual prices
    using the subscription period in force on the last day of the month:
    valid_from <= month_end < valid_to   (valid_to is null for a period that is still open)
MRR = 0 if no period is in force.
```

- **Subscription periods** (`int_subscription_periods`): each non-cancel event opens a period
  that ends, exclusively, when the customer's next event takes effect. A cancel event closes the
  previous period without opening a new one. Periods of one customer never overlap
  (`assert_no_overlapping_subscription_periods`).
- **Spine.** `fct_mrr` has a row for every month from the customer's first subscription month to
  the last month of data, **including zero-MRR months after churn**, so the previous row is always
  the previous calendar month.
- **Mid-month plan changes:** the state on the last day of the month counts for the whole month.
  A change effective on the last day counts in that month; a change effective on the 1st counts
  from that month. MRR is a run-rate snapshot, not recognised revenue, so there is no daily
  proration.
- **Annual plans** are normalised to a month by dividing by 12 (the `monthly_amount` macro is the
  single definition). An annual customer therefore contributes the same MRR every month although
  they pay once a year.
- **Failed payments:** while an invoice is in dunning (up to 14 days) the subscription is still
  active and **still counts in MRR**. MRR drops to zero only when the subscription is cancelled
  after the last failed retry. Cash actually collected is a separate measure
  (`dim_customers.lifetime_paid_usd`).
- **Price change:** MRR uses the price the customer is billed at, so grandfathered customers
  carry the old price until they change plan.
- **Rounding:** each period's MRR is rounded to cents once. Every aggregate is an exact sum of
  those values.
- **Not in scope:** discounts, coupons, taxes, refunds, one-off charges (none exist in the data).

## MRR movements

**Model:** `fct_mrr_movements`. **Grain:** customer x month, only for months in which month-end
MRR changed. `previous = MRR(customer, month - 1)`, which is 0 in the customer's first month;
`current = MRR(customer, month)`.

| Movement | Condition | Amount (`mrr_change_usd`) |
| --- | --- | --- |
| `new` | previous = 0, current > 0, and this is the customer's first month with MRR (`cohort_month`) | current (positive) |
| `reactivation` | previous = 0, current > 0, and the customer had MRR in an earlier month | current (positive) |
| `expansion` | previous > 0 and current > previous | current - previous (positive) |
| `contraction` | previous > 0 and 0 < current < previous | current - previous (negative) |
| `churn` | previous > 0 and current = 0 | -previous (negative) |

The five conditions are mutually exclusive and, for rows where MRR changed, exhaustive
(`assert_mrr_movements_exclusive_and_exhaustive`). Months without a change have no row.

- **Movements come from MRR, not from event types.** An `upgrade` event followed by an
  involuntary cancellation in the same month is one `churn` movement, measured from the previous
  month's MRR. With the default data there are 1,661 `upgrade` events and 1,650 `expansion`
  movements for this reason.
- **Reactivation window:** there is no time limit. A customer who returns after any number of
  zero-MRR months is a reactivation, never a second `new`. A cancellation and a return within the
  same calendar month never show up at month end, so they produce neither churn nor reactivation.
- **`churn_reason`** on churn rows is the `cancel_reason` of the cancel event that took effect
  during that month: `voluntary` or `payment_failed`.

## MRR bridge

**Model:** `rpt_mrr_bridge`. **Grain:** calendar month.

```
starting_mrr(month) = ending_mrr(month - 1)          (0 in the first month)
ending_mrr(month)   = sum of MRR(customer, month)
ending_mrr = starting_mrr + new + expansion + reactivation + contraction + churned
             (contraction and churned are negative)
ending_customers = starting_customers + new_customers + reactivated_customers - churned_customers
```

Both identities are enforced every month by `assert_mrr_bridge_reconciles`.
`involuntary_churned_mrr_usd` is the part of `churned_mrr_usd` with
`churn_reason = 'payment_failed'`. It is a subset, so never add it to the bridge.

| Rate | Formula | Notes |
| --- | --- | --- |
| `mrr_growth_rate` | (ending - starting) / starting MRR | null when starting MRR is 0 |
| `logo_churn_rate` | churned_customers / starting_customers | monthly |
| `gross_mrr_churn_rate` | -(contraction + churned) / starting MRR | ignores expansion |
| `net_mrr_churn_rate` | -(contraction + churned + expansion) / starting MRR | negative = "net negative churn"; reactivation excluded |
| `quick_ratio` | (new + expansion + reactivation) / -(contraction + churned) | above 1 means MRR grows |

Trailing-period figures in the report are pooled over the months: for example, average monthly
logo churn = sum of churned customers / sum of starting customers over the 12 months.

## Cohort retention

**Model:** `rpt_cohort_retention`. **Grain:** cohort month x months since cohort start.

- **Cohort** (`cohort_month`): the customer's first month with month-end MRR above zero.
  `months_since_cohort_start = date_diff('month', cohort_month, month)`, 0 for the cohort month.
- **Logo retention** = cohort customers with MRR > 0 at the end of the month / cohort size. A
  reactivated customer counts as retained again in the months they pay. It can never exceed 100%
  and is exactly 100% in month 0 (`assert_logo_retention_at_most_100_pct`).
- **Net revenue retention (NRR)** = the cohort's MRR at the end of the month / the cohort's MRR at
  the end of month 0. It includes expansion, contraction, churn and reactivation, so it can exceed
  100%.
- **Right-censoring:** a cohort only has rows for months that exist in the data, which gives the
  triangle in the heatmap. The report's pooled curves divide summed active customers (or MRR) by
  summed cohort size (or month-0 MRR) over the cohorts old enough to reach each month.

## Unit economics

**Model:** `rpt_unit_economics`. **Grain:** acquisition channel, plus one blended
`all_channels` row. Do not add the blended row to the channel rows.

- **Window:** the trailing `unit_economics_lookback_months` (default 12) calendar months that end
  with the last month of data.
- **Channel attribution:** first touch. A customer belongs to the channel of their original
  signup: the cleaned `utm_source`, mapped by the `channel_mapping` seed. Reactivations are not
  new customers.

| Metric | Formula |
| --- | --- |
| `marketing_spend_usd` | spend in the window |
| `new_customers` | customers whose `cohort_month` falls in the window |
| `cac_usd` | marketing_spend_usd / new_customers; **null when spend is 0** (organic customers are not free, their cost is unmeasured). The blended CAC is total spend / all new customers, organic included. |
| `arpa_usd` | sum of MRR over active customer-months / number of active customer-months in the window (customers of any cohort) |
| `monthly_logo_churn_rate` | customer-months that churned / customer-months that started the month with MRR > 0, pooled over the window |
| `gross_margin_pct` | **assumption**, project variable `gross_margin_pct` = 0.80. The data has no cost of revenue. |
| `expected_lifetime_months` | 1 / monthly_logo_churn_rate |
| `ltv_usd` | arpa_usd x gross_margin_pct / monthly_logo_churn_rate |
| `cac_payback_months` | cac_usd / (arpa_usd x gross_margin_pct) |
| `ltv_to_cac_ratio` | ltv_usd / cac_usd |

**The churn assumption behind LTV:** churn is assumed constant over a customer's life at the
observed pooled monthly logo churn rate, which gives a geometric lifetime with a mean of 1 / churn
months. LTV is undiscounted, ignores future expansion and contraction (ARPA is held flat), and
has no lifetime cap. It pairs ARPA with logo (customer) churn, the standard simple LTV; a
revenue-churn version would also credit expansion.

Edge cases: spend in a month usually converts 2-4 weeks later, which the trailing window ignores;
a channel with zero churn would have a null LTV; CAC counts media spend only (no salaries or
tools).

## Funnel

**Model:** `rpt_funnel`. **Grain:** signup month x acquisition channel.

| Metric | Formula |
| --- | --- |
| `signups` | signups in the month |
| `trials` | of those, signups that started a trial (at most one per signup) |
| `paid_customers` | of those, signups that converted to a paid subscription by the end of data |
| `signup_to_trial_rate` | trials / signups |
| `trial_to_paid_rate` | paid_customers / trials (measured on trials, not signups) |
| `signup_to_paid_rate` | paid_customers / signups |
| `is_complete_cohort` | last day of the signup month + `funnel_maturity_days` (30) <= last day of data |

Trials last 14 days and start at most four days after signup, so 30 days after the end of the
signup month every trial in the cohort has ended. The latest cohorts are flagged incomplete because their conversions are still
missing (right-censoring), and the report only uses complete cohorts.

## Cash versus MRR

`dim_customers.lifetime_paid_usd` sums successful payments after duplicate webhook deliveries are
removed in `stg_payments`. Cash and MRR differ on purpose: an annual customer pays 12 months
upfront but contributes one twelfth of that to MRR each month, and an invoice in dunning is
counted in MRR before any cash arrives.
