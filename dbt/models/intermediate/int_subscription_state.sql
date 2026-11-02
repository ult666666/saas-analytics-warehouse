-- One row per customer whose first subscription has started: the plan, seats, price and status
-- in force on the last day of data. The snapshot snp_subscription_state records how this state
-- changes from load to load (SCD type 2).

with periods as (
    select * from {{ ref('int_subscription_periods') }}
),

prices as (
    select * from {{ ref('stg_plans') }}
),

as_of as (
    select max(date_day) as as_of_date
    from {{ ref('int_date_spine') }}
),

started as (
    select
        periods.*,
        as_of.as_of_date,
        row_number() over (
            partition by periods.customer_id
            order by periods.valid_from desc
        ) as recency
    from periods
    cross join as_of
    where periods.valid_from <= as_of.as_of_date
),

latest as (
    -- The most recent period that had started; it is still in force unless it has ended.
    select
        *,
        valid_to is null or valid_to > as_of_date as is_in_force
    from started
    where recency = 1
)

select
    latest.customer_id,
    case when latest.is_in_force then 'active' else 'cancelled' end as subscription_status,
    latest.plan_price_id,
    latest.plan_code,
    latest.billing_interval,
    latest.seats,
    prices.unit_amount_usd,
    case when latest.is_in_force then latest.mrr_usd else 0 end as mrr_usd,
    -- When this state began: the period's start, or the day it ended for a cancelled
    -- subscription. The snapshot uses it as the start of each version's validity window.
    cast(
        case when latest.is_in_force then latest.valid_from else latest.valid_to end as timestamp
    ) as state_started_at
from latest
inner join prices
    on latest.plan_price_id = prices.plan_price_id
