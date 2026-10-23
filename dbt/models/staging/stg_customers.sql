with source as (
    select * from {{ source('raw', 'customers') }}
),

renamed as (
    select
        customer_id,
        signup_id,
        cast(created_at as timestamp) as converted_at
    from source
)

select * from renamed
