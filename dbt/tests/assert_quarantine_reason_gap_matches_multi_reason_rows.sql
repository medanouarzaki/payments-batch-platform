-- The six reason counters in data_quality_daily can sum to more than
-- quarantined_row_count because a row can trigger more than one reason at
-- once; that gap is measured but was not explained until this test. This
-- checks the explanation directly: the gap for a date must equal the sum,
-- over that date's rows in quarantine_transactions, of their reason count
-- minus one. Written in this general form, not as a count of two-reason
-- rows specifically, so it keeps holding if a row ever carries three or
-- more reasons at once.

with reason_sum as (

    select
        ingestion_date,
        quarantined_missing_key_count + quarantined_missing_currency_count
            + quarantined_unknown_currency_count + quarantined_non_positive_amount_count
            + quarantined_invalid_amount_count + quarantined_invalid_timestamp_count
            - quarantined_row_count as counted_gap
    from {{ ref('data_quality_daily') }}

),

measured_gap as (

    select
        ingestion_date,
        sum(len(quarantine_reasons) - 1) as measured_gap
    from {{ ref('quarantine_transactions') }}
    group by 1

)

select
    reason_sum.ingestion_date,
    reason_sum.counted_gap,
    coalesce(measured_gap.measured_gap, 0) as measured_gap
from reason_sum
left join measured_gap
    on reason_sum.ingestion_date = measured_gap.ingestion_date
where reason_sum.counted_gap <> coalesce(measured_gap.measured_gap, 0)
