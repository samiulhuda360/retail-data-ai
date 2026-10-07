{#-
  Schema contract for a source feed: fails with one row per column that appeared without being modelled
  (schema drift) or disappeared. Columns are read from the warehouse at run time, so it works on any adapter.
-#}
{% test columns_match_contract(model, expected_columns) %}
{%- set actual = [] -%}
{%- if execute -%}
    {%- for col in adapter.get_columns_in_relation(model) -%}{%- do actual.append(col.name | lower) -%}{%- endfor -%}
{%- endif -%}
{%- set expected = expected_columns | map('lower') | list -%}
select column_name, issue from (
    {%- for col in actual if col not in expected %}
    select '{{ col }}' as column_name, 'unexpected column (not in the contract)' as issue union all
    {%- endfor %}
    {%- for col in expected if col not in actual %}
    select '{{ col }}' as column_name, 'missing column' as issue union all
    {%- endfor %}
    select null as column_name, null as issue
) as diff
where column_name is not null
{% endtest %}
