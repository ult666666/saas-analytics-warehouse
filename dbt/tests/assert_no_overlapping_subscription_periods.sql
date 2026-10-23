-- A customer is on at most one subscription at a time, so two of their periods may never
-- overlap. Periods are half-open [valid_from, valid_to); an open period runs to the end.

with periods as (
    select * from {{ ref('int_subscription_periods') }}
)

select
    earlier.customer_id,
    earlier.subscription_period_id as earlier_period_id,
    later.subscription_period_id as later_period_id,
    earlier.valid_from as earlier_valid_from,
    earlier.valid_to as earlier_valid_to,
    later.valid_from as later_valid_from
from periods as earlier
inner join periods as later
    on earlier.customer_id = later.customer_id
    and earlier.subscription_period_id != later.subscription_period_id
    and earlier.valid_from <= later.valid_from
    and (earlier.valid_to is null or earlier.valid_to > later.valid_from)
