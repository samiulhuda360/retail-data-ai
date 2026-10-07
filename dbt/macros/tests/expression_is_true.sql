{#- Fails with every row where the boolean expression is false. Combine with `config: where:` to scope it. -#}
{% test expression_is_true(model, expression) %}
select * from {{ model }} where not ({{ expression }})
{% endtest %}
