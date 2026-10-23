-- Billing integrity: a paid invoice has exactly one successful payment, an open or
-- uncollectible invoice has none, and every attempt charges the full invoice amount.
-- This only holds after stg_payments drops redelivered webhooks.

with invoices as (
    select * from {{ ref('stg_invoices') }}
),

payments as (
    select * from {{ ref('stg_payments') }}
),

summary as (
    select
        invoices.invoice_id,
        invoices.invoice_status,
        count(payments.payment_id) filter (
            where payments.payment_status = 'succeeded'
        ) as successful_payments,
        count(payments.payment_id) filter (
            where payments.amount_usd != invoices.amount_due_usd
        ) as mismatched_amounts
    from invoices
    left join payments
        on invoices.invoice_id = payments.invoice_id
    group by invoices.invoice_id, invoices.invoice_status
)

select *
from summary
where (invoice_status = 'paid' and successful_payments != 1)
    or (invoice_status != 'paid' and successful_payments != 0)
    or mismatched_amounts > 0
