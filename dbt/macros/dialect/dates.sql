{#-
  The few places where DuckDB and Databricks SQL differ, behind adapter.dispatch.
  Models call these macros, so the same project compiles for either warehouse.
-#}

{% macro parse_date(column, source_format) -%}
    {{ return(adapter.dispatch('parse_date', 'acme_retail')(column, source_format)) }}
{%- endmacro %}

{#- source_format uses one vocabulary: 'yyyymmdd', 'dd/mm/yyyy' or 'yyyy-mm-dd' -#}
{% macro default__parse_date(column, source_format) -%}
    {%- set fmt = {'yyyymmdd': 'yyyyMMdd', 'dd/mm/yyyy': 'dd/MM/yyyy', 'yyyy-mm-dd': 'yyyy-MM-dd'}[source_format] -%}
    to_date({{ column }}, '{{ fmt }}')
{%- endmacro %}

{% macro duckdb__parse_date(column, source_format) -%}
    {%- set fmt = {'yyyymmdd': '%Y%m%d', 'dd/mm/yyyy': '%d/%m/%Y', 'yyyy-mm-dd': '%Y-%m-%d'}[source_format] -%}
    cast(strptime({{ column }}, '{{ fmt }}') as date)
{%- endmacro %}


{% macro date_series(start_date, end_date) -%}
    {{ return(adapter.dispatch('date_series', 'acme_retail')(start_date, end_date)) }}
{%- endmacro %}

{% macro default__date_series(start_date, end_date) -%}
    select explode(sequence(to_date('{{ start_date }}'), to_date('{{ end_date }}'), interval 1 day)) as date_day
{%- endmacro %}

{% macro duckdb__date_series(start_date, end_date) -%}
    select cast(unnest(generate_series(date '{{ start_date }}', date '{{ end_date }}', interval 1 day)) as date) as date_day
{%- endmacro %}


{#- The replay clock: the as-of time, as a timestamp literal. -#}
{% macro as_of() -%}
    cast('{{ var("as_of") }}' as timestamp)
{%- endmacro %}
