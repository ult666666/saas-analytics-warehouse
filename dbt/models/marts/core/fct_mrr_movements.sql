-- One row per customer per month in which their month-end MRR changed, classified into
-- exactly one movement type. Months without a change have no row.

with mrr as (
    select * from {{ ref('fct_mrr') }}
),

cancel_events as (
    select
        customer_id,
        cast(date_trunc('month', effective_date) as date) as month_start,
        cancel_reason,
        row_number() over (
            partition by customer_id, date_trunc('month', effective_date)
            order by effective_date desc, occurred_at desc
        ) as recency_rank
    from {{ ref('stg_subscription_events') }}
    where event_type = 'cancel'
),

cancellations as (
    -- The reason behind a churn is the last cancel event that took effect during the month.
    select
        customer_id,
        month_start,
        cancel_reason
    from cancel_events
    where recency_rank = 1
),

changes as (
    select
        customer_id,
        month_start,
        cohort_month,
        previous_mrr_usd,
        mrr_usd,
        mrr_change_usd
    from mrr
    where mrr_usd != previous_mrr_usd
),

classified as (
    select
        *,
        case
            when previous_mrr_usd = 0 and month_start = cohort_month then 'new'
            when previous_mrr_usd = 0 then 'reactivation'
            when mrr_usd = 0 then 'churn'
            when mrr_usd > previous_mrr_usd then 'expansion'
            else 'contraction'
        end as movement_type
    from changes
)

select
    classified.customer_id,
    classified.month_start,
    classified.movement_type,
    classified.previous_mrr_usd,
    classified.mrr_usd,
    classified.mrr_change_usd,
    case
        when classified.movement_type = 'churn' then cancellations.cancel_reason
    end as churn_reason
from classified
left join cancellations
    on classified.customer_id = cancellations.customer_id
    and classified.month_start = cancellations.month_start
