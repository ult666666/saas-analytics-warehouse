{{
    config(
        materialized='incremental',
        unique_key='invoice_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

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
        status as invoice_status,
        cast(updated_at as timestamp) as updated_at
    from source
),

recent as (
    select * from renamed
    where {{ incremental_lookback('updated_at') }}
),

latest_versions as (
    -- An invoice arrives again when its status changes (open, then paid or uncollectible).
    -- Keep its newest version; the unique key replaces the older one already loaded.
    select *
    from recent
    qualify row_number() over (partition by invoice_id order by updated_at desc) = 1
)

select * from latest_versions
