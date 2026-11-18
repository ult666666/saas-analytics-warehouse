-- Replaying a later webhook must never move a staged payment's first receipt forward.
with first_receipts as (
    select
        payment_id,
        min(cast(received_at as timestamp)) as first_received_at
    from {{ source('raw', 'payments') }}
    group by payment_id
)

select
    payments.payment_id,
    payments.received_at,
    first_receipts.first_received_at
from {{ ref('stg_payments') }} as payments
inner join first_receipts
    on payments.payment_id = first_receipts.payment_id
where payments.received_at is distinct from first_receipts.first_received_at
