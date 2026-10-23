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

deduplicated as (
    -- The payment webhook delivers at least once, so a payment can arrive twice.
    -- Keep the first delivery of each payment_id.
    select *
    from renamed
    qualify row_number() over (partition by payment_id order by received_at) = 1
)

select * from deduplicated
