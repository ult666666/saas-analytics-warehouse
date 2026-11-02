{% macro incremental_lookback(column) -%}
    {#-
        A filter for incremental staging models. On an incremental run it keeps the source rows
        whose `column` is at most `incremental_lookback_days` older than the newest value already
        in the model, so rows that arrived late are picked up and replace their earlier copies
        through the unique key. A full refresh, or a first run, keeps every row. Rows that arrive
        later than the window are missed until the next full refresh.
    -#}
    {%- if is_incremental() -%}
        {{ column }} >= coalesce(
            (
                select max(loaded.{{ column }})
                    - interval '{{ var("incremental_lookback_days") }} days'
                from {{ this }} as loaded
            ),
            {{ column }}
        )
    {%- else -%}
        true
    {%- endif -%}
{%- endmacro %}
