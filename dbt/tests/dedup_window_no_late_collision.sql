with window_bounds as (

    select max(ingestion_date) - interval (({{ var('dedup_window_days') }}) - 1) day as window_start
    from {{ ref('stg_transactions') }}

)

select stg_transactions.transaction_id, stg_transactions.ingestion_date
from {{ ref('stg_transactions') }} as stg_transactions
cross join window_bounds
join {{ ref('int_transactions_deduped') }} as int_transactions_deduped
    on int_transactions_deduped.transaction_id = stg_transactions.transaction_id
where stg_transactions.is_valid
  and stg_transactions.ingestion_date < window_bounds.window_start
  and stg_transactions.row_hash <> int_transactions_deduped.row_hash
  and int_transactions_deduped.source_ingestion_date >= window_bounds.window_start
