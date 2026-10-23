{% macro date_spine(datepart, start_date, end_date) %}
    {#-
        One row per `datepart` (day, month, ...) from start_date to end_date, both inclusive.
        start_date and end_date are SQL expressions: date literals, casts or scalar subqueries.
        Written for DuckDB's generate_series; dbt_utils.date_spine is the cross-database
        equivalent, but this project deliberately has no package dependencies.
    -#}
    select
        cast(unnest(generate_series(
            cast({{ start_date }} as date),
            cast({{ end_date }} as date),
            interval 1 {{ datepart }}
        )) as date) as date_{{ datepart }}
{% endmacro %}
