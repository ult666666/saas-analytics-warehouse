{{
    config(
        materialized='incremental',
        unique_key=['spend_date', 'channel'],
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with source as (
    select * from {{ source('raw', 'marketing_spend') }}
),

renamed as (
    select
        cast(spend_date as date) as spend_date,
        channel,
        {{ cents_to_dollars('spend_cents') }} as spend_usd
    from source
),

recent as (
    -- Daily spend, one row per day and channel. It defines the reporting calendar
    -- (int_date_spine), so it is the one daily feed that is never late.
    select * from renamed
    where {{ incremental_lookback('spend_date') }}
)

select * from recent
