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
)

select * from renamed
