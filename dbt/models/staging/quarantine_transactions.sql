{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='ingestion_date'
  )
}}

with staging_rows as (

    select *
    from {{ ref('stg_transactions') }}
    where not is_valid
    {% if var('ingestion_date', none) %}
    and ingestion_date = date '{{ var('ingestion_date') }}'
    {% endif %}

),

final as (

    select
        row_hash,
        transaction_id,
        ingestion_date,
        event_date_utc,
        event_timestamp_utc,
        amount,
        currency_code,
        status,
        channel,
        source_batch_id,
        ingested_at,
        list_filter(dq_flags, x -> list_contains({{ quarantine_reasons() }}, x)) as quarantine_reasons
    from staging_rows

)

select * from final
