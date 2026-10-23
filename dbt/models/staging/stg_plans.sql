with source as (
    select * from {{ source('raw', 'plans') }}
),

renamed as (
    select
        plan_price_id,
        plan_code,
        plan_name,
        cast(plan_tier as integer) as plan_tier,
        billing_interval,
        {{ cents_to_dollars('unit_amount_cents') }} as unit_amount_usd,
        currency,
        cast(valid_from as date) as valid_from,
        cast(valid_to as date) as valid_to
    from source
)

select * from renamed
