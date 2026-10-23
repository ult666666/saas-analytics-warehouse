{% macro monthly_amount(amount, billing_interval) -%}
    {#-
        Normalises an amount billed per `billing_interval` to one month, rounded to cents.
        This is the single definition of how annual prices count towards MRR.
        An unknown interval yields null, which the not_null tests on MRR columns catch.
    -#}
    cast(
        {{ amount }} / case {{ billing_interval }} when 'month' then 1 when 'year' then 12 end
        as decimal(18, 2)
    )
{%- endmacro %}
