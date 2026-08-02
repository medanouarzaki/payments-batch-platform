-- The previous version of this test asserted
-- received_row_count = deduplicated_row_count + quarantined_row_count + duplicate_removed_count.
-- data_quality_daily computes duplicate_removed_count as
-- valid_row_count - deduplicated_row_count, so substituting that definition
-- turns the assertion into received_row_count = valid_row_count + quarantined_row_count,
-- which holds for any row count because every row is either valid or
-- quarantined by construction. The test could never fail.
--
-- This version measures duplicates independently, directly on
-- stg_transactions, and compares that measurement to what data_quality_daily
-- reports.

with independent_duplicate_count as (

    select
        ingestion_date,
        count(*) filter (where is_valid)
            - count(distinct transaction_id) filter (where is_valid) as duplicates_measured
    from {{ ref('stg_transactions') }}
    group by ingestion_date

)

select
    data_quality_daily.ingestion_date,
    data_quality_daily.duplicate_removed_count,
    independent_duplicate_count.duplicates_measured
from {{ ref('data_quality_daily') }} as data_quality_daily
inner join independent_duplicate_count
    on data_quality_daily.ingestion_date = independent_duplicate_count.ingestion_date
where data_quality_daily.duplicate_removed_count <> independent_duplicate_count.duplicates_measured
