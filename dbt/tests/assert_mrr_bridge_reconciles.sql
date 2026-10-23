-- The MRR bridge must reconcile every month:
--   starting MRR + new + expansion + reactivation + contraction + churn = ending MRR,
-- ending MRR must equal the sum of customer-level MRR, every month must start where the
-- previous month ended, and the customer counts must roll forward the same way.
-- Returns the months that break any rule.

with bridge as (
    select * from {{ ref('rpt_mrr_bridge') }}
),

customer_level as (
    select
        month_start,
        sum(mrr_usd) as total_mrr_usd,
        count(*) filter (where is_active) as active_customers
    from {{ ref('fct_mrr') }}
    group by month_start
),

checks as (
    select
        bridge.month_start,
        bridge.starting_mrr_usd
        + bridge.new_mrr_usd
        + bridge.expansion_mrr_usd
        + bridge.reactivation_mrr_usd
        + bridge.contraction_mrr_usd
        + bridge.churned_mrr_usd as reconstructed_ending_mrr_usd,
        bridge.ending_mrr_usd,
        coalesce(customer_level.total_mrr_usd, 0) as customer_level_mrr_usd,
        bridge.starting_mrr_usd,
        coalesce(
            lag(bridge.ending_mrr_usd) over (order by bridge.month_start), 0
        ) as previous_ending_mrr_usd,
        bridge.starting_customers
        + bridge.new_customers
        + bridge.reactivated_customers
        - bridge.churned_customers as reconstructed_ending_customers,
        bridge.ending_customers,
        coalesce(customer_level.active_customers, 0) as customer_level_customers
    from bridge
    left join customer_level
        on bridge.month_start = customer_level.month_start
)

select *
from checks
where reconstructed_ending_mrr_usd != ending_mrr_usd
    or ending_mrr_usd != customer_level_mrr_usd
    or starting_mrr_usd != previous_ending_mrr_usd
    or reconstructed_ending_customers != ending_customers
    or ending_customers != customer_level_customers
