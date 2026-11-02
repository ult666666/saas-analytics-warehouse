-- A customer's snapshot versions never overlap and leave no gaps: each validity window ends
-- exactly where the next one begins, every window has positive length, and only the newest
-- version is still open.

with versions as (
    select
        customer_id,
        dbt_valid_from,
        dbt_valid_to,
        lead(dbt_valid_from) over (
            partition by customer_id order by dbt_valid_from
        ) as next_valid_from
    from {{ ref('snp_subscription_state') }}
)

select
    customer_id,
    dbt_valid_from,
    dbt_valid_to,
    next_valid_from
from versions
where
    dbt_valid_to <= dbt_valid_from
    or dbt_valid_to is distinct from next_valid_from
