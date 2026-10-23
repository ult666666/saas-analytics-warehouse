{% test unique_combination_of_columns(model, combination_of_columns) %}
    {#- Fails for every combination of the given columns that appears more than once. -#}
    {%- set columns = combination_of_columns | join(', ') %}
    select
        {{ columns }},
        count(*) as occurrences
    from {{ model }}
    group by {{ columns }}
    having count(*) > 1
{% endtest %}
