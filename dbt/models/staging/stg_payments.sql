{{
    config(
        materialized='incremental',
        unique_key='payment_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with source as (
    select * from {{ source('raw', 'payments') }}
),

renamed as (
    select
        payment_id,
        invoice_id,
        cast(attempt_number as integer) as attempt_number,
        cast(attempted_at as timestamp) as attempted_at,
        {{ cents_to_dollars('amount_cents') }} as amount_usd,
        status as payment_status,
        failure_code,
        cast(received_at as timestamp) as received_at
    from source
),

recent as (
    -- received_at is when the webhook reached the warehouse. The lookback window keeps the
    -- first delivery of a payment in view when its redelivery arrives.
    select * from renamed
    where {{ incremental_lookback('received_at') }}
),

deduplicated as (
    -- The payment webhook delivers at least once, so a payment can arrive twice.
    -- Keep the first delivery of each payment_id.
    select *
    from recent
    qualify row_number() over (partition by payment_id order by received_at) = 1
)

select * from deduplicated
