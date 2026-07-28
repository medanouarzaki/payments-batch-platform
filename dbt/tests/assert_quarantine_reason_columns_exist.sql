-- data_quality_daily copies the reason list into a Jinja variable because dbt cannot
-- expand a macro's array literal into a loop; this test is what stops that copy from
-- silently drifting from quarantine_reasons() if the macro is ever edited.

{% set reasons = quarantine_reasons() %}
{% set reason_names = reasons.replace('[', '').replace(']', '').replace("'", '').replace('\n', ' ').split(',') %}

with columns as (
    select lower(column_name) as column_name
    from information_schema.columns
    where table_name = 'data_quality_daily'
)

select missing.reason
from (
    {% for reason in reason_names %}
    select '{{ reason.strip() }}' as reason
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
) as missing
where not exists (
    select 1 from columns
    where columns.column_name = 'quarantined_' || lower(missing.reason) || '_count'
)
