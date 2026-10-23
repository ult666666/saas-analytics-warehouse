-- MRR is never negative, at any grain.

select
    'int_subscription_periods' as model_name,
    subscription_period_id as record_key,
    mrr_usd
from {{ ref('int_subscription_periods') }}
where mrr_usd < 0

union all

select
    'fct_mrr' as model_name,
    customer_id || ' ' || cast(month_start as varchar) as record_key,
    mrr_usd
from {{ ref('fct_mrr') }}
where mrr_usd < 0 or previous_mrr_usd < 0

union all

select
    'rpt_mrr_bridge' as model_name,
    cast(month_start as varchar) as record_key,
    ending_mrr_usd as mrr_usd
from {{ ref('rpt_mrr_bridge') }}
where starting_mrr_usd < 0 or ending_mrr_usd < 0

union all

select
    'rpt_cohort_retention' as model_name,
    cast(cohort_month as varchar) || ' +' || months_since_cohort_start as record_key,
    mrr_usd
from {{ ref('rpt_cohort_retention') }}
where mrr_usd < 0 or cohort_starting_mrr_usd < 0
