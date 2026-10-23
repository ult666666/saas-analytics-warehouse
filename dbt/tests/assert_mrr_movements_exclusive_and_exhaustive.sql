-- Every customer-month whose MRR changed must have exactly one movement row, and every
-- movement row must satisfy exactly one category definition: the one it is labelled with.
-- The definitions are written out again here, independently of the model's case expression.

with mrr as (
    select * from {{ ref('fct_mrr') }}
),

movements as (
    select * from {{ ref('fct_mrr_movements') }}
),

definitions as (
    select
        customer_id,
        month_start,
        previous_mrr_usd = 0 and mrr_usd > 0 and month_start = cohort_month as is_new,
        previous_mrr_usd = 0 and mrr_usd > 0 and month_start > cohort_month as is_reactivation,
        previous_mrr_usd > 0 and mrr_usd > previous_mrr_usd as is_expansion,
        previous_mrr_usd > 0 and mrr_usd > 0 and mrr_usd < previous_mrr_usd as is_contraction,
        previous_mrr_usd > 0 and mrr_usd = 0 as is_churn
    from mrr
    where mrr_usd != previous_mrr_usd
),

compared as (
    select
        coalesce(definitions.customer_id, movements.customer_id) as customer_id,
        coalesce(definitions.month_start, movements.month_start) as month_start,
        movements.movement_type,
        cast(definitions.is_new as integer)
        + cast(definitions.is_reactivation as integer)
        + cast(definitions.is_expansion as integer)
        + cast(definitions.is_contraction as integer)
        + cast(definitions.is_churn as integer) as matching_categories,
        case movements.movement_type
            when 'new' then definitions.is_new
            when 'reactivation' then definitions.is_reactivation
            when 'expansion' then definitions.is_expansion
            when 'contraction' then definitions.is_contraction
            when 'churn' then definitions.is_churn
        end as matches_own_definition
    from definitions
    full outer join movements
        on definitions.customer_id = movements.customer_id
        and definitions.month_start = movements.month_start
)

select *
from compared
where movement_type is null  -- an MRR change without a movement row
    or matching_categories is null  -- a movement row without an MRR change
    or matching_categories != 1  -- categories must be mutually exclusive and exhaustive
    or not matches_own_definition  -- the row carries the wrong label
