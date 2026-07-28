{% macro parse_amount(column) %}
    try_cast(replace(replace({{ column }}, ' ', ''), ',', '.') as decimal(18,2))
{% endmacro %}
