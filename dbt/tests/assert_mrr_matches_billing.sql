-- MRR comes from subscription events, invoices from the billing system. They must agree:
-- for every customer-month with MRR, the invoice in force on the month-end day, normalised
-- to one month, equals the customer's MRR. Invoices are billed at list price (unit price x
-- seats), so the price book has to agree as well.
--
-- "In force" means the most recent invoice whose service period covers the day. After an
-- involuntary cancellation the unpaid invoice keeps its nominal period (up to a year for
-- annual plans), which can overlap the invoice of a later reactivation.

with active_months as (
    select customer_id, month_start, month_end, mrr_usd
    from {{ ref('fct_mrr') }}
    where is_active
),

invoices as (
    select
        invoices.invoice_id,
        invoices.customer_id,
        invoices.period_start,
        invoices.period_end,
        invoices.amount_due_usd,
        prices.unit_amount_usd * invoices.seats as list_amount_usd,
        {{ monthly_amount('invoices.amount_due_usd', 'prices.billing_interval') }}
            as monthly_invoiced_usd
    from {{ ref('stg_invoices') }} as invoices
    inner join {{ ref('stg_plans') }} as prices
        on invoices.plan_price_id = prices.plan_price_id
),

invoice_in_force as (
    select
        active_months.customer_id,
        active_months.month_start,
        active_months.mrr_usd,
        invoices.invoice_id,
        invoices.monthly_invoiced_usd,
        invoices.amount_due_usd,
        invoices.list_amount_usd
    from active_months
    left join invoices
        on active_months.customer_id = invoices.customer_id
        and invoices.period_start <= active_months.month_end
        and invoices.period_end > active_months.month_end
    qualify row_number() over (
        partition by active_months.customer_id, active_months.month_start
        order by invoices.period_start desc
    ) = 1
)

select *
from invoice_in_force
where invoice_id is null
    or monthly_invoiced_usd != mrr_usd
    or amount_due_usd != list_amount_usd
