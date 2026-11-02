-- The snapshot's current versions are exactly the state int_subscription_state reports now:
-- the same customers, with the same plan, seats, price, MRR, status and start.

with current_versions as (
    select
        customer_id,
        subscription_status,
        plan_price_id,
        seats,
        unit_amount_usd,
        mrr_usd,
        state_started_at
    from {{ ref('snp_subscription_state') }}
    where dbt_valid_to is null
),

current_state as (
    select
        customer_id,
        subscription_status,
        plan_price_id,
        seats,
        unit_amount_usd,
        mrr_usd,
        state_started_at
    from {{ ref('int_subscription_state') }}
),

only_in_snapshot as (
    select * from current_versions
    except
    select * from current_state
),

only_in_model as (
    select * from current_state
    except
    select * from current_versions
)

select
    'only in the snapshot' as side,
    customer_id,
    subscription_status,
    plan_price_id,
    seats,
    unit_amount_usd,
    mrr_usd,
    state_started_at
from only_in_snapshot
union all
select
    'only in int_subscription_state' as side,
    customer_id,
    subscription_status,
    plan_price_id,
    seats,
    unit_amount_usd,
    mrr_usd,
    state_started_at
from only_in_model
