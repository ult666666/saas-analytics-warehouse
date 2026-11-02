-- Every customer in the snapshot has exactly one current version (no dbt_valid_to).

select
    customer_id,
    count(*) filter (where dbt_valid_to is null) as current_versions
from {{ ref('snp_subscription_state') }}
group by customer_id
having count(*) filter (where dbt_valid_to is null) != 1
