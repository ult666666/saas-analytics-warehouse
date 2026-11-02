-- Wherever the snapshot has a version in force on a month end, that version agrees with
-- fct_mrr's month-end state: the same MRR and, while active, the same price and seats.
-- fct_mrr is rebuilt from the full event log, so this checks the recorded history against
-- an independent derivation.

with versions as (
    select * from {{ ref('snp_subscription_state') }}
),

as_of as (
    select max(date_day) as as_of_date
    from {{ ref('int_date_spine') }}
),

month_ends as (
    select
        fct_mrr.customer_id,
        fct_mrr.month_end,
        fct_mrr.plan_price_id,
        fct_mrr.seats,
        fct_mrr.mrr_usd
    from {{ ref('fct_mrr') }} as fct_mrr
    cross join as_of
    where fct_mrr.month_end <= as_of.as_of_date
),

compared as (
    select
        month_ends.customer_id,
        month_ends.month_end,
        month_ends.plan_price_id,
        month_ends.seats,
        month_ends.mrr_usd,
        versions.subscription_status,
        versions.plan_price_id as snapshot_plan_price_id,
        versions.seats as snapshot_seats,
        versions.mrr_usd as snapshot_mrr_usd
    from month_ends
    inner join versions
        on month_ends.customer_id = versions.customer_id
        and cast(month_ends.month_end as timestamp) >= versions.dbt_valid_from
        and (
            versions.dbt_valid_to is null
            or cast(month_ends.month_end as timestamp) < versions.dbt_valid_to
        )
)

select *
from compared
where
    mrr_usd != snapshot_mrr_usd
    or (
        subscription_status = 'active'
        and (
            plan_price_id is distinct from snapshot_plan_price_id
            or seats is distinct from snapshot_seats
        )
    )
