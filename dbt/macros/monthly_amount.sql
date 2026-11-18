{% macro monthly_amount(amount, billing_interval) -%}
    {#-
        Normalises an amount billed per `billing_interval` to one month, rounded to cents.
        This is the single definition of how annual prices count towards MRR.
        An unknown interval yields null, which the not_null tests on MRR columns catch.
    -#}
    cast(case {{ billing_interval }}
        when 'month' then {{ amount }}
        when 'year' then (
            -- Round half a cent away from zero before the integer division by twelve.
            (cast(cast({{ amount }} as decimal(38, 2)) * 100 as hugeint)
                + 6 * sign({{ amount }})) // 12
        ) * 0.01
    end as decimal(18, 2))
{%- endmacro %}
