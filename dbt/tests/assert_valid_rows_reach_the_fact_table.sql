-- Comparing counts per ingestion date would hide a specific failure mode: a row
-- that never finds a duplicate to blame at its own date could in principle
-- share its transaction_id with a row landed on a different date, so a loss and
-- a duplicate could net out within one date's total while still showing up in
-- the global count. This test is deliberately global, not grouped by date.
--
-- It exists because data_quality_daily's duplicate_removed_count is computed by
-- subtraction (valid_row_count minus deduplicated_row_count): a silent loss of
-- valid rows in the fact table, with no actual duplicate behind it, shows up in
-- that subtraction as extra duplicates removed, and nothing checking
-- data_quality_daily's own accounting can tell the two apart.

with valid_staging as (

    select count(distinct transaction_id) as n
    from {{ ref('stg_transactions') }}
    where is_valid

),

fact as (

    select count(*) as n
    from {{ ref('fct_transactions') }}

)

select
    valid_staging.n as valid_distinct_transaction_ids,
    fact.n as fact_transactions_row_count
from valid_staging
cross join fact
where valid_staging.n <> fact.n
