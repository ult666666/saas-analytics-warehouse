with source as (
    select * from {{ source('raw', 'marketing_spend') }}
),

renamed as (
    select
        cast(spend_date as date) as spend_date,
        channel,
        {{ cents_to_dollars('spend_cents') }} as spend_usd
    from source
)

select * from renamed
