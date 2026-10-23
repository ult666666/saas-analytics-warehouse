{% macro generate_schema_name(custom_schema_name, node) -%}
    {#-
        Use the folder's custom schema (staging, intermediate, marts, seeds) as-is instead of
        dbt's default "<target schema>_<custom schema>". This is a single-developer local
        warehouse; a shared warehouse would keep per-developer prefixes in dev targets.
    -#}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
