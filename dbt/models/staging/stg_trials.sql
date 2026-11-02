{{
    config(
        materialized='incremental',
        unique_key='trial_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with source as (
    select * from {{ source('raw', 'trials') }}
),

renamed as (
    select
        trial_id,
        signup_id,
        cast(started_at as timestamp) as trial_started_at,
        cast(ends_at as timestamp) as trial_ends_at
    from source
),

recent as (
    select * from renamed
    where {{ incremental_lookback('trial_started_at') }}
)

select * from recent
