{#- Converts a local-currency amount to NZD with the day's AUD->NZD rate. NZD passes through unchanged. -#}
{% macro to_nzd(amount, currency, aud_nzd_rate) -%}
    case when {{ currency }} = 'AUD' then {{ amount }} * {{ aud_nzd_rate }} else {{ amount }} end
{%- endmacro %}
