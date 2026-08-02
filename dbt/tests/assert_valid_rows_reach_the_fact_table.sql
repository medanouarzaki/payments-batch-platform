-- This test only covers valid rows within the deduplication window: a
-- partition ingested older than the window is dropped silently by the
-- incremental clause, which test_backfill_reverse_order_drops_partitions_older_than_window
-- and test_late_ingestion_beyond_window_is_silently_dropped exercise
-- deliberately. This test does not cover that loss; it remains a known
-- limitation, not a guarantee.
--
-- The window size below (7) is written in clear rather than read from
-- var('dedup_window_days'): a test that imports the constant it is meant to
-- police tests nothing. It deliberately duplicates dbt_project.yml's
-- dedup_window_days, and a change to one requires the same change to the
-- other. int_transactions_deduped computes its own window_start as
-- max_ingestion_date - (dedup_window_days - 1) days, so a 7-day inclusive
-- window is a 6-day offset below, matching the model exactly.
--
-- The test exists because data_quality_daily's duplicate_removed_count is
-- computed by subtraction (valid_row_count minus deduplicated_row_count): a
-- silent loss of valid rows in the fact table, with no actual duplicate
-- behind it, shows up in that subtraction as extra duplicates removed, and
-- nothing checking data_quality_daily's own accounting can tell the two
-- apart.

with window_bound as (

    select max(ingestion_date) - interval 6 day as window_start
    from {{ ref('stg_transactions') }}

),

valid_ids_in_window as (

    select distinct
        stg_transactions.transaction_id,
        stg_transactions.ingestion_date
    from {{ ref('stg_transactions') }}
    cross join window_bound
    where stg_transactions.is_valid
        and stg_transactions.ingestion_date >= window_bound.window_start

),

fact_ids as (

    select distinct transaction_id
    from {{ ref('fct_transactions') }}

)

select
    valid_ids_in_window.transaction_id,
    valid_ids_in_window.ingestion_date
from valid_ids_in_window
left join fact_ids
    on valid_ids_in_window.transaction_id = fact_ids.transaction_id
where fact_ids.transaction_id is null
