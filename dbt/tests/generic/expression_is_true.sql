{% test expression_is_true(model, expression, column_name=none) %}
    {#-
        Fails for every row where the boolean SQL expression is false (nulls do not fail).
        When attached to a column, dbt passes column_name; the expression is still written
        out in full, e.g. "spend_usd >= 0", so it reads the same at model and column level.
    -#}
    select *
    from {{ model }}
    where not ({{ expression }})
{% endtest %}
