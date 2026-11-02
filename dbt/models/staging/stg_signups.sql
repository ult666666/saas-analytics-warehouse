{{
    config(
        materialized='incremental',
        unique_key='signup_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with source as (
    select * from {{ source('raw', 'signups') }}
),

cleaned as (
    select
        signup_id,
        cast(created_at as timestamp) as signed_up_at,
        cast(created_at as date) as signup_date,
        -- Tracking parameters are typed by hand, so normalise case and whitespace.
        -- A signup without a utm_source is direct traffic.
        coalesce(nullif(lower(trim(utm_source)), ''), 'direct') as utm_source,
        upper(trim(country_code)) as country_code,
        company_size
    from source
),

recent as (
    -- Incremental runs reprocess the lookback window, which absorbs late signups.
    select * from cleaned
    where {{ incremental_lookback('signed_up_at') }}
)

select * from recent
