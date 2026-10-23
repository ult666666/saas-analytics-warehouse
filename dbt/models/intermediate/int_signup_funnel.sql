-- One row per signup with its acquisition channel and how far it got in the funnel.

with signups as (
    select * from {{ ref('stg_signups') }}
),

channel_mapping as (
    select * from {{ ref('channel_mapping') }}
),

trials as (
    select * from {{ ref('stg_trials') }}
),

customers as (
    select * from {{ ref('stg_customers') }}
)

select
    signups.signup_id,
    signups.signed_up_at,
    signups.signup_date,
    cast(date_trunc('month', signups.signup_date) as date) as signup_month,
    signups.utm_source,
    -- Unknown sources stay visible as 'unmapped' and fail the accepted_values test.
    coalesce(channel_mapping.channel, 'unmapped') as channel,
    signups.country_code,
    signups.company_size,
    trials.trial_id,
    trials.trial_started_at,
    customers.customer_id,
    customers.converted_at,
    trials.trial_id is not null as started_trial,
    customers.customer_id is not null as converted_to_paid
from signups
left join channel_mapping
    on signups.utm_source = channel_mapping.utm_source
left join trials
    on signups.signup_id = trials.signup_id
left join customers
    on signups.signup_id = customers.signup_id
