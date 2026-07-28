with quarantine_counts as (

    select ingestion_date, count(*) as quarantine_rows
    from {{ ref('quarantine_transactions') }}
    group by ingestion_date

),

invalid_counts as (

    select ingestion_date, count(*) as invalid_rows
    from {{ ref('stg_transactions') }}
    where not is_valid
    group by ingestion_date

),

mismatched_counts as (

    select
        coalesce(quarantine_counts.ingestion_date, invalid_counts.ingestion_date) as ingestion_date,
        coalesce(quarantine_counts.quarantine_rows, 0) as quarantine_rows,
        coalesce(invalid_counts.invalid_rows, 0) as invalid_rows
    from quarantine_counts
    full outer join invalid_counts using (ingestion_date)
    where coalesce(quarantine_counts.quarantine_rows, 0) <> coalesce(invalid_counts.invalid_rows, 0)

),

orphan_row_hashes as (

    select quarantine_transactions.row_hash
    from {{ ref('quarantine_transactions') }} as quarantine_transactions
    left join {{ ref('stg_transactions') }} as stg_transactions
        on stg_transactions.row_hash = quarantine_transactions.row_hash
    where stg_transactions.row_hash is null

)

select ingestion_date, quarantine_rows, invalid_rows, null as orphan_row_hash
from mismatched_counts

union all

select null as ingestion_date, null as quarantine_rows, null as invalid_rows, row_hash as orphan_row_hash
from orphan_row_hashes
