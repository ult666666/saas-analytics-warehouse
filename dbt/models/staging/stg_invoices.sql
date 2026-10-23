with source as (
    select * from {{ source('raw', 'invoices') }}
),

renamed as (
    select
        invoice_id,
        customer_id,
        cast(invoice_date as date) as invoice_date,
        cast(period_start as date) as period_start,
        -- Exclusive: the period covers period_start up to the day before period_end.
        cast(period_end as date) as period_end,
        plan_price_id,
        cast(seats as integer) as seats,
        {{ cents_to_dollars('amount_due_cents') }} as amount_due_usd,
        status as invoice_status
    from source
)

select * from renamed
