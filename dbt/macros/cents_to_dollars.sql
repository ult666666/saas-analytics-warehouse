{% macro cents_to_dollars(column_name) -%}
    {#- Raw money columns are integer cents; the warehouse works in dollars with two decimals. -#}
    cast(cast({{ column_name }} as bigint) * 0.01 as decimal(18, 2))
{%- endmacro %}
