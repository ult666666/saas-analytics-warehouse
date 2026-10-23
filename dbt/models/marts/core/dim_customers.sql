with funnel as (
    select * from {{ ref('int_signup_funnel') }}
    where customer_id is not null
),

mrr as (
    select * from {{ ref('fct_mrr') }}
),

last_month as (
    select max(month_start) as month_start from mrr
),

first_month_state as (
    select
        customer_id,
        plan_code as first_plan_code,
        billing_interval as first_billing_interval,
        mrr_usd as first_mrr_usd
    from mrr
    where month_start = cohort_month
),

current_state as (
    select
        mrr.customer_id,
        mrr.plan_code as current_plan_code,
        mrr.mrr_usd as current_mrr_usd
    from mrr
    inner join last_month
        on mrr.month_start = last_month.month_start
),

mrr_history as (
    select
        customer_id,
        min(cohort_month) as cohort_month,
        count(*) filter (where is_active) as active_months,
        count(*) filter (where previous_mrr_usd > 0 and mrr_usd = 0) as churn_count
    from mrr
    group by customer_id
),

collected_cash as (
    select
        invoices.customer_id,
        sum(payments.amount_usd) as lifetime_paid_usd
    from {{ ref('stg_payments') }} as payments
    inner join {{ ref('stg_invoices') }} as invoices
        on payments.invoice_id = invoices.invoice_id
    where payments.payment_status = 'succeeded'
    group by invoices.customer_id
)

select
    funnel.customer_id,
    funnel.signup_id,
    funnel.channel as acquisition_channel,
    funnel.utm_source,
    funnel.country_code,
    funnel.company_size,
    funnel.signup_date,
    funnel.trial_started_at,
    funnel.converted_at,
    mrr_history.cohort_month,
    first_month_state.first_plan_code,
    first_month_state.first_billing_interval,
    first_month_state.first_mrr_usd,
    current_state.current_plan_code,
    coalesce(current_state.current_mrr_usd, 0) as current_mrr_usd,
    coalesce(current_state.current_mrr_usd, 0) > 0 as is_active,
    mrr_history.active_months,
    mrr_history.churn_count,
    coalesce(collected_cash.lifetime_paid_usd, 0) as lifetime_paid_usd
from funnel
left join mrr_history
    on funnel.customer_id = mrr_history.customer_id
left join first_month_state
    on funnel.customer_id = first_month_state.customer_id
left join current_state
    on funnel.customer_id = current_state.customer_id
left join collected_cash
    on funnel.customer_id = collected_cash.customer_id
