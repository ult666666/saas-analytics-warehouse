-- Unit economics per acquisition channel over a trailing window of complete months, plus a
-- blended 'all_channels' row. Assumptions (see docs/METRICS.md): gross margin is a constant
-- project variable and the observed monthly logo churn rate stays constant over a lifetime.

{% set lookback_months = var('unit_economics_lookback_months') %}
{% set gross_margin = var('gross_margin_pct') %}

with window_bounds as (
    select
        cast(
            date_trunc('month', max(date_day)) - to_months({{ lookback_months }} - 1) as date
        ) as first_month,
        cast(date_trunc('month', max(date_day)) as date) as last_month,
        max(date_day) as last_date
    from {{ ref('dim_date') }}
),

channels as (
    select distinct channel from {{ ref('channel_mapping') }}
),

spend as (
    select
        spend.channel,
        sum(spend.spend_usd) as marketing_spend_usd
    from {{ ref('stg_marketing_spend') }} as spend
    cross join window_bounds
    where spend.spend_date between window_bounds.first_month and window_bounds.last_date
    group by spend.channel
),

customer_months as (
    select
        customers.acquisition_channel as channel,
        mrr.month_start,
        mrr.cohort_month,
        mrr.mrr_usd,
        mrr.previous_mrr_usd,
        mrr.is_active
    from {{ ref('fct_mrr') }} as mrr
    inner join {{ ref('dim_customers') }} as customers
        on mrr.customer_id = customers.customer_id
    cross join window_bounds
    where mrr.month_start between window_bounds.first_month and window_bounds.last_month
),

channel_totals as (
    select
        coalesce(channels.channel, 'all_channels') as channel,
        coalesce(sum(spend.marketing_spend_usd), 0) as marketing_spend_usd
    from channels
    left join spend
        on channels.channel = spend.channel
    group by rollup(channels.channel)
),

channel_activity as (
    select
        coalesce(channel, 'all_channels') as channel,
        count(*) filter (where month_start = cohort_month) as new_customers,
        count(*) filter (where is_active) as active_customer_months,
        sum(mrr_usd) filter (where is_active) as active_mrr_usd,
        count(*) filter (where previous_mrr_usd > 0) as customer_months_at_risk,
        count(*) filter (where previous_mrr_usd > 0 and mrr_usd = 0) as churned_customer_months
    from customer_months
    group by rollup(channel)
),

metrics as (
    select
        channel_totals.channel,
        channel_totals.marketing_spend_usd,
        channel_activity.new_customers,
        -- No spend means no CAC: organic customers are not free, their cost is unmeasured.
        case
            when channel_totals.marketing_spend_usd > 0
                then channel_totals.marketing_spend_usd / nullif(channel_activity.new_customers, 0)
        end as cac_usd,
        channel_activity.active_mrr_usd
        / nullif(channel_activity.active_customer_months, 0) as arpa_usd,
        channel_activity.churned_customer_months
        / nullif(channel_activity.customer_months_at_risk, 0) as monthly_logo_churn_rate
    from channel_totals
    left join channel_activity
        on channel_totals.channel = channel_activity.channel
)

select
    channel,
    marketing_spend_usd,
    new_customers,
    cast(cac_usd as decimal(18, 2)) as cac_usd,
    cast(arpa_usd as decimal(18, 2)) as arpa_usd,
    {{ gross_margin }} as gross_margin_pct,
    round(monthly_logo_churn_rate, 4) as monthly_logo_churn_rate,
    round(1 / nullif(monthly_logo_churn_rate, 0), 1) as expected_lifetime_months,
    cast(arpa_usd * {{ gross_margin }} / nullif(monthly_logo_churn_rate, 0) as decimal(18, 2))
        as ltv_usd,
    round(cac_usd / nullif(arpa_usd * {{ gross_margin }}, 0), 1) as cac_payback_months,
    round(arpa_usd * {{ gross_margin }} / nullif(monthly_logo_churn_rate, 0) / cac_usd, 2)
        as ltv_to_cac_ratio
from metrics
