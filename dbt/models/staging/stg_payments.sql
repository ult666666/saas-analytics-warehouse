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

recent_keys as (
    -- The window selects payments to revisit. A later delivery can qualify its
    -- payment_id even when the first receipt is already outside the window.
    select payment_id from renamed
    where {{ incremental_lookback('received_at') }}
)

select renamed.*
from renamed
semi join recent_keys
    on renamed.payment_id is not distinct from recent_keys.payment_id
qualify row_number() over (partition by renamed.payment_id order by renamed.received_at) = 1
