{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='ingestion_date'
  )
}}

-- Reason names mirror dbt/macros/quarantine_reasons.sql, read and verified at write
-- time; dbt cannot expand a macro's array literal into a Jinja list for column
-- generation, so list_contains(quarantine_reasons(), ...) stays the single filtering
-- source of truth and this list is kept in sync with it by hand.
{% set quarantine_reason_names = ['MISSING_KEY', 'MISSING_CURRENCY', 'UNKNOWN_CURRENCY', 'NON_POSITIVE_AMOUNT', 'INVALID_AMOUNT', 'INVALID_TIMESTAMP'] %}

-- A date's duplicate count can change when a later run picks a different dedup
-- winner for an old ingestion date, so touched dates are recomputed from the full
-- history of each source, not filtered to the rows the latest ingestion added.

with window_bounds as (

    select
        max(ingestion_date) as max_ingestion_date,
        max(ingestion_date) - interval (({{ var('dedup_window_days') }}) - 1) day as window_start
    from {{ ref('stg_transactions') }}

),

touched_ingestion_dates as (

    select distinct stg_transactions.ingestion_date
    from {{ ref('stg_transactions') }} as stg_transactions
    cross join window_bounds
    {% if is_incremental() %}
    where stg_transactions.ingestion_date >= window_bounds.window_start
    {% endif %}

),

staging_stats as (

    select
        stg_transactions.ingestion_date,
        count(*) as received_row_count,
        count(*) filter (where stg_transactions.is_valid) as valid_row_count,
        count(*) filter (where not stg_transactions.is_valid) as quarantined_row_count
    from {{ ref('stg_transactions') }} as stg_transactions
    inner join touched_ingestion_dates
        on stg_transactions.ingestion_date = touched_ingestion_dates.ingestion_date
    group by 1

),

fact_stats as (

    select
        fct_transactions.source_ingestion_date as ingestion_date,
        count(*) as deduplicated_row_count,
        count(*) filter (
            where fct_transactions.source_ingestion_date > fct_transactions.event_date_utc
        ) as late_row_count
    from {{ ref('fct_transactions') }} as fct_transactions
    inner join touched_ingestion_dates
        on fct_transactions.source_ingestion_date = touched_ingestion_dates.ingestion_date
    group by 1

),

quarantine_stats as (

    select
        quarantine_transactions.ingestion_date,
        {% for reason in quarantine_reason_names %}
        count(*) filter (
            where list_contains(quarantine_transactions.quarantine_reasons, '{{ reason }}')
        ) as quarantined_{{ reason.lower() }}_count{% if not loop.last %},{% endif %}
        {% endfor %}
    from {{ ref('quarantine_transactions') }} as quarantine_transactions
    inner join touched_ingestion_dates
        on quarantine_transactions.ingestion_date = touched_ingestion_dates.ingestion_date
    group by 1

),

final as (

    select
        touched_ingestion_dates.ingestion_date,
        coalesce(staging_stats.received_row_count, 0) as received_row_count,
        coalesce(staging_stats.valid_row_count, 0) as valid_row_count,
        coalesce(staging_stats.quarantined_row_count, 0) as quarantined_row_count,
        -- Duplicates are counted by subtraction, not by comparing row hashes: an exact
        -- duplicate shares its winner's row_hash by construction, so a hash comparison
        -- would miss it, exactly as in reconciliation_by_ingestion_date.sql.
        coalesce(staging_stats.valid_row_count, 0) - coalesce(fact_stats.deduplicated_row_count, 0)
            as duplicate_removed_count,
        coalesce(fact_stats.deduplicated_row_count, 0) as deduplicated_row_count,
        coalesce(fact_stats.late_row_count, 0) as late_row_count,
        case
            when coalesce(staging_stats.received_row_count, 0) = 0 then null
            else round(
                cast(coalesce(staging_stats.quarantined_row_count, 0) as double)
                / staging_stats.received_row_count,
                6
            )
        end as rejection_rate,
        case
            when coalesce(fact_stats.deduplicated_row_count, 0) = 0 then null
            else round(
                cast(coalesce(fact_stats.late_row_count, 0) as double)
                / fact_stats.deduplicated_row_count,
                6
            )
        end as late_rate,
        {% for reason in quarantine_reason_names %}
        coalesce(quarantine_stats.quarantined_{{ reason.lower() }}_count, 0)
            as quarantined_{{ reason.lower() }}_count{% if not loop.last %},{% endif %}
        {% endfor %}
    from touched_ingestion_dates
    left join staging_stats
        on touched_ingestion_dates.ingestion_date = staging_stats.ingestion_date
    left join fact_stats
        on touched_ingestion_dates.ingestion_date = fact_stats.ingestion_date
    left join quarantine_stats
        on touched_ingestion_dates.ingestion_date = quarantine_stats.ingestion_date

)

select * from final
