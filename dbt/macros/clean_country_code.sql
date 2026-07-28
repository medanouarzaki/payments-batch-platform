{% macro clean_country_code(column) %}
    nullif(upper(trim({{ column }})), '')
{% endmacro %}
