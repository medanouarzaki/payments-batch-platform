{% macro row_hash(columns) %}
    md5(
        {%- for column in columns %}
        coalesce(cast({{ column }} as varchar), '<NULL>'){% if not loop.last %} || '|' || {% endif %}
        {%- endfor %}
    )
{% endmacro %}
