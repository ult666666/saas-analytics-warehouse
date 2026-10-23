-- A funnel can only narrow: trials <= signups and paid customers <= trials in every cohort.

select
    signup_month,
    channel,
    signups,
    trials,
    paid_customers
from {{ ref('rpt_funnel') }}
where trials > signups
    or paid_customers > trials
