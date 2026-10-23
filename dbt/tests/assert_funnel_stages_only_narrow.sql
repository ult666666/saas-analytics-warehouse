-- A funnel can only narrow: trials <= signups and paid customers <= trials in every cohort.

select *
from {{ ref('rpt_funnel') }}
where trials > signups
    or paid_customers > trials
