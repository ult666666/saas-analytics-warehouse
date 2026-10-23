-- Signup -> trial -> paid conversion by signup month and acquisition channel.

with funnel as (
    select * from {{ ref('int_signup_funnel') }}
),

last_date as (
    select max(date_day) as last_date from {{ ref('dim_date') }}
),

cohorts as (
    select
        signup_month,
        channel,
        count(*) as signups,
        count(*) filter (where started_trial) as trials,
        count(*) filter (where converted_to_paid) as paid_customers
    from funnel
    group by signup_month, channel
)

select
    cohorts.signup_month,
    cohorts.channel,
    cohorts.signups,
    cohorts.trials,
    cohorts.paid_customers,
    round(cohorts.trials / cohorts.signups, 4) as signup_to_trial_rate,
    round(cohorts.paid_customers / nullif(cohorts.trials, 0), 4) as trial_to_paid_rate,
    round(cohorts.paid_customers / cohorts.signups, 4) as signup_to_paid_rate,
    -- Recent cohorts have not had time to finish their trials; flag them so that
    -- conversion rates are only compared across complete cohorts.
    last_day(cohorts.signup_month) + {{ var('funnel_maturity_days') }} <= last_date.last_date
        as is_complete_cohort
from cohorts
cross join last_date
