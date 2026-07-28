{% macro country_lookup() %}
    select alpha_2 as code, alpha_2 from {{ ref('dim_country') }}
    union all
    select alpha_3 as code, alpha_2 from {{ ref('dim_country') }}
{% endmacro %}
