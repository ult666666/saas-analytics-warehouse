-- One row per day covered by the extract. The generator writes marketing spend for every
-- day of the simulated window, so its first and last dates define the reporting calendar.

{% set first_day %}(select min(spend_date) from {{ ref('stg_marketing_spend') }}){% endset %}
{% set last_day %}(select max(spend_date) from {{ ref('stg_marketing_spend') }}){% endset %}

with spine as (
    {{ date_spine('day', first_day, last_day) }}
)

select date_day
from spine
