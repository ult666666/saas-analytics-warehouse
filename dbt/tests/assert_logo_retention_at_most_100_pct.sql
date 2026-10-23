-- Logo retention counts cohort customers who still pay, so it can never exceed 100% (net
-- revenue retention can, through expansion). Month 0 is 100% by definition.

select
    cohort_month,
    months_since_cohort_start,
    cohort_customers,
    active_customers,
    logo_retention_rate
from {{ ref('rpt_cohort_retention') }}
where active_customers > cohort_customers
    or logo_retention_rate > 1
    or (months_since_cohort_start = 0 and logo_retention_rate != 1)
