-- Company-level MRR bridge: for every month, starting MRR plus the movements equals ending MRR.

with calendar_months as (
    select distinct month_start from {{ ref('dim_date') }}
),

monthly_mrr as (
    select
        month_start,
        sum(mrr_usd) as ending_mrr_usd,
        count(*) filter (where is_active) as ending_customers
    from {{ ref('fct_mrr') }}
    group by month_start
),

monthly_movements as (
    select
        month_start,
        coalesce(sum(mrr_change_usd) filter (where movement_type = 'new'), 0) as new_mrr_usd,
        coalesce(sum(mrr_change_usd) filter (where movement_type = 'expansion'), 0)
            as expansion_mrr_usd,
        coalesce(sum(mrr_change_usd) filter (where movement_type = 'reactivation'), 0)
            as reactivation_mrr_usd,
        coalesce(sum(mrr_change_usd) filter (where movement_type = 'contraction'), 0)
            as contraction_mrr_usd,
        coalesce(sum(mrr_change_usd) filter (where movement_type = 'churn'), 0) as churned_mrr_usd,
        coalesce(
            sum(mrr_change_usd) filter (
                where movement_type = 'churn' and churn_reason = 'payment_failed'
            ),
            0
        ) as involuntary_churned_mrr_usd,
        count(*) filter (where movement_type = 'new') as new_customers,
        count(*) filter (where movement_type = 'reactivation') as reactivated_customers,
        count(*) filter (where movement_type = 'churn') as churned_customers
    from {{ ref('fct_mrr_movements') }}
    group by month_start
),

ending_balances as (
    select
        calendar_months.month_start,
        coalesce(monthly_mrr.ending_mrr_usd, 0) as ending_mrr_usd,
        coalesce(monthly_mrr.ending_customers, 0) as ending_customers
    from calendar_months
    left join monthly_mrr
        on calendar_months.month_start = monthly_mrr.month_start
),

bridge as (
    select
        ending_balances.month_start,
        coalesce(
            lag(ending_balances.ending_mrr_usd) over (order by ending_balances.month_start), 0
        ) as starting_mrr_usd,
        coalesce(monthly_movements.new_mrr_usd, 0) as new_mrr_usd,
        coalesce(monthly_movements.expansion_mrr_usd, 0) as expansion_mrr_usd,
        coalesce(monthly_movements.reactivation_mrr_usd, 0) as reactivation_mrr_usd,
        coalesce(monthly_movements.contraction_mrr_usd, 0) as contraction_mrr_usd,
        coalesce(monthly_movements.churned_mrr_usd, 0) as churned_mrr_usd,
        coalesce(monthly_movements.involuntary_churned_mrr_usd, 0) as involuntary_churned_mrr_usd,
        ending_balances.ending_mrr_usd,
        coalesce(
            lag(ending_balances.ending_customers) over (order by ending_balances.month_start), 0
        ) as starting_customers,
        coalesce(monthly_movements.new_customers, 0) as new_customers,
        coalesce(monthly_movements.reactivated_customers, 0) as reactivated_customers,
        coalesce(monthly_movements.churned_customers, 0) as churned_customers,
        ending_balances.ending_customers
    from ending_balances
    left join monthly_movements
        on ending_balances.month_start = monthly_movements.month_start
)

select
    month_start,
    starting_mrr_usd,
    new_mrr_usd,
    expansion_mrr_usd,
    reactivation_mrr_usd,
    contraction_mrr_usd,
    churned_mrr_usd,
    involuntary_churned_mrr_usd,
    new_mrr_usd + expansion_mrr_usd + reactivation_mrr_usd + contraction_mrr_usd
        + churned_mrr_usd as net_new_mrr_usd,
    ending_mrr_usd,
    starting_customers,
    new_customers,
    reactivated_customers,
    churned_customers,
    ending_customers,
    round((ending_mrr_usd - starting_mrr_usd) / nullif(starting_mrr_usd, 0), 4)
        as mrr_growth_rate,
    round(churned_customers / nullif(starting_customers, 0), 4) as logo_churn_rate,
    round(-(contraction_mrr_usd + churned_mrr_usd) / nullif(starting_mrr_usd, 0), 4)
        as gross_mrr_churn_rate,
    round(
        -(contraction_mrr_usd + churned_mrr_usd + expansion_mrr_usd) / nullif(starting_mrr_usd, 0),
        4
    ) as net_mrr_churn_rate,
    round(
        (new_mrr_usd + expansion_mrr_usd + reactivation_mrr_usd)
        / nullif(-(contraction_mrr_usd + churned_mrr_usd), 0),
        2
    ) as quick_ratio
from bridge
