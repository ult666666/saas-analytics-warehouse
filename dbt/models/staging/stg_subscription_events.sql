with source as (
    select * from {{ source('raw', 'subscription_events') }}
),

renamed as (
    select
        event_id,
        customer_id,
        event_type,
        cast(occurred_at as timestamp) as occurred_at,
        cast(effective_date as date) as effective_date,
        plan_price_id,
        cast(seats as integer) as seats,
        cancel_reason
    from source
)

select * from renamed
