with prices as (
    select * from {{ ref('stg_plans') }}
)

select
    plan_price_id,
    plan_code,
    plan_name,
    plan_tier,
    billing_interval,
    unit_amount_usd,
    {{ monthly_amount('unit_amount_usd', 'billing_interval') }} as mrr_per_seat_usd,
    currency,
    valid_from,
    valid_to,
    valid_to is null as is_current_price
from prices
