with days as (
    select date_day from {{ ref('int_date_spine') }}
)

select
    date_day,
    cast(date_trunc('month', date_day) as date) as month_start,
    last_day(date_day) as month_end,
    cast(date_trunc('quarter', date_day) as date) as quarter_start,
    year(date_day) as year_number,
    quarter(date_day) as quarter_number,
    month(date_day) as month_number,
    monthname(date_day) as month_name,
    isodow(date_day) as iso_day_of_week,
    dayname(date_day) as day_name,
    isodow(date_day) in (6, 7) as is_weekend,
    date_day = last_day(date_day) as is_month_end
from days
