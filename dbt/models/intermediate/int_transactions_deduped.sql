{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='transaction_id'
  )
}}

with window_bounds as (

    select
        max(ingestion_date) as max_ingestion_date,
        max(ingestion_date) - interval (({{ var('dedup_window_days') }}) - 1) day as window_start
    from {{ ref('stg_transactions') }}

),

candidate_rows as (

    select stg_transactions.*
    from {{ ref('stg_transactions') }} as stg_transactions
    cross join window_bounds
    where stg_transactions.is_valid
    {% if is_incremental() %}
    and stg_transactions.ingestion_date >= window_bounds.window_start
    {% endif %}

),

ranked as (

    select
        candidate_rows.*,
        count(*) over (partition by candidate_rows.transaction_id) as duplicate_count
    from candidate_rows
    qualify row_number() over (
        partition by candidate_rows.transaction_id
        order by candidate_rows.event_timestamp_utc desc, candidate_rows.ingested_at desc, candidate_rows.row_hash asc
    ) = 1

),

final as (

    select
        transaction_id,
        event_timestamp_utc,
        event_date_utc,
        amount,
        currency_code,
        debtor_account,
        creditor_account,
        debtor_country,
        creditor_country,
        status,
        channel,
        rejection_reason,
        source_batch_id,
        ingested_at,
        ingestion_date as source_ingestion_date,
        dq_flags,
        is_valid,
        row_hash,
        duplicate_count
    from ranked

)

select * from final
