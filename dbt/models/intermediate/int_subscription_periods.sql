-- Turns the event log into periods: each event opens a period that lasts until the customer's
-- next event takes effect. Periods opened by a cancel event carry no subscription and are
-- dropped, so every row here is a time range in which the customer was paying.

with events as (
    select * from {{ ref('stg_subscription_events') }}
),

prices as (
    select * from {{ ref('stg_plans') }}
),

sequenced as (
    select
        event_id,
        customer_id,
        event_type,
        effective_date,
        plan_price_id,
        seats,
        lead(effective_date) over (
            partition by customer_id
            order by effective_date, occurred_at, event_id
        ) as next_effective_date
    from events
),

periods as (
    select
        sequenced.event_id as subscription_period_id,
        sequenced.customer_id,
        sequenced.event_type as opened_by_event_type,
        sequenced.effective_date as valid_from,
        sequenced.next_effective_date as valid_to,
        sequenced.plan_price_id,
        prices.plan_code,
        prices.plan_tier,
        prices.billing_interval,
        sequenced.seats,
        {{ monthly_amount('sequenced.seats * prices.unit_amount_usd', 'prices.billing_interval') }}
            as mrr_usd
    from sequenced
    inner join prices
        on sequenced.plan_price_id = prices.plan_price_id
    where sequenced.event_type != 'cancel'
)

select
    subscription_period_id,
    customer_id,
    opened_by_event_type,
    valid_from,
    valid_to,
    valid_to is null as is_open,
    plan_price_id,
    plan_code,
    plan_tier,
    billing_interval,
    seats,
    mrr_usd
from periods
