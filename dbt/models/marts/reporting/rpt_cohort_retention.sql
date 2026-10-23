-- Logo and net revenue retention by monthly cohort (first month with MRR) and months since.

with mrr as (
    select * from {{ ref('fct_mrr') }}
    where months_since_cohort_start >= 0
),

cohort_sizes as (
    select
        cohort_month,
        count(*) as cohort_customers,
        sum(mrr_usd) as cohort_starting_mrr_usd
    from mrr
    where months_since_cohort_start = 0
    group by cohort_month
),

cohort_activity as (
    select
        cohort_month,
        months_since_cohort_start,
        count(*) filter (where is_active) as active_customers,
        sum(mrr_usd) as mrr_usd
    from mrr
    group by cohort_month, months_since_cohort_start
)

select
    cohort_activity.cohort_month,
    cohort_activity.months_since_cohort_start,
    cohort_sizes.cohort_customers,
    cohort_activity.active_customers,
    round(cohort_activity.active_customers / cohort_sizes.cohort_customers, 4)
        as logo_retention_rate,
    cohort_sizes.cohort_starting_mrr_usd,
    cohort_activity.mrr_usd,
    round(cohort_activity.mrr_usd / cohort_sizes.cohort_starting_mrr_usd, 4)
        as net_revenue_retention_rate
from cohort_activity
inner join cohort_sizes
    on cohort_activity.cohort_month = cohort_sizes.cohort_month
