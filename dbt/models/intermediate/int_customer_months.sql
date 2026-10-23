-- The customer x month spine: every calendar month from the month a customer's first
-- subscription starts to the last month of data, including months after they churn.
-- A gap-free spine is what lets fct_mrr compare each month with the previous one.

with customer_first_months as (
    select
        customer_id,
        cast(date_trunc('month', min(valid_from)) as date) as first_month
    from {{ ref('int_subscription_periods') }}
    group by customer_id
),

calendar_months as (
    select distinct cast(date_trunc('month', date_day) as date) as month_start
    from {{ ref('int_date_spine') }}
)

select
    customer_first_months.customer_id,
    calendar_months.month_start,
    last_day(calendar_months.month_start) as month_end
from customer_first_months
inner join calendar_months
    on customer_first_months.first_month <= calendar_months.month_start
