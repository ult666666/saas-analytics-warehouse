-- Monthly recurring revenue per customer per month, measured on the last day of the month.
-- The spine has no gaps, so previous_mrr_usd is always the MRR of the calendar month before.

with customer_months as (
    select * from {{ ref('int_customer_months') }}
),

periods as (
    select * from {{ ref('int_subscription_periods') }}
),

month_end_snapshot as (
    -- The period in force on the last day of the month determines the month's MRR.
    -- Periods of one customer never overlap, so at most one period matches.
    select
        customer_months.customer_id,
        customer_months.month_start,
        customer_months.month_end,
        periods.plan_price_id,
        periods.plan_code,
        periods.billing_interval,
        periods.seats,
        coalesce(periods.mrr_usd, 0) as mrr_usd
    from customer_months
    left join periods
        on customer_months.customer_id = periods.customer_id
        and periods.valid_from <= customer_months.month_end
        and (periods.valid_to is null or periods.valid_to > customer_months.month_end)
),

with_history as (
    select
        *,
        lag(mrr_usd, 1, 0) over (
            partition by customer_id order by month_start
        ) as previous_mrr_usd,
        min(case when mrr_usd > 0 then month_start end) over (
            partition by customer_id
        ) as cohort_month
    from month_end_snapshot
)

select
    customer_id,
    month_start,
    month_end,
    cohort_month,
    date_diff('month', cohort_month, month_start) as months_since_cohort_start,
    plan_price_id,
    plan_code,
    billing_interval,
    seats,
    mrr_usd,
    previous_mrr_usd,
    mrr_usd - previous_mrr_usd as mrr_change_usd,
    mrr_usd > 0 as is_active
from with_history
