-- Month-end facts are published once the daily calendar covers both boundaries.
-- The date spine is continuous, including days with no customer activity.
with bounds as (
    select
        cast(date_trunc('month', date_day) as date) as month_start,
        min(date_day) as first_day,
        max(date_day) as last_day_seen
    from {{ ref('int_date_spine') }}
    group by month_start
)

select
    month_start,
    last_day_seen as month_end
from bounds
where first_day = month_start and last_day_seen = last_day(month_start)
