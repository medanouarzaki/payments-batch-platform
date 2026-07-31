{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='event_date_utc'
  )
}}

-- The incremental window only identifies which event dates the current run touched;
-- it is never used to filter the rows being aggregated. A date's total must reflect
-- every fact row ever assigned to it, not just the ones the latest ingestion added.

with window_bounds as (

    select
        max(source_ingestion_date) as max_ingestion_date,
        max(source_ingestion_date) - interval (({{ var('dedup_window_days') }}) - 1) day as window_start
    from {{ ref('fct_transactions') }}

),

touched_event_dates as (

    select distinct fct_transactions.event_date_utc
    from {{ ref('fct_transactions') }} as fct_transactions
    cross join window_bounds
    {% if is_incremental() %}
    where fct_transactions.source_ingestion_date >= window_bounds.window_start
    {% endif %}

),

-- No filter on source_ingestion_date here: every row for a touched date is reread,
-- so the aggregate reflects the date's full history, not the fraction the run added.
scoped_facts as (

    select fct_transactions.*
    from {{ ref('fct_transactions') }} as fct_transactions
    inner join touched_event_dates
        on fct_transactions.event_date_utc = touched_event_dates.event_date_utc

),

final as (

    select
        event_date_utc,
        debtor_country,
        status,
        count(*) as transaction_count,
        sum(amount_eur) as amount_eur_total,
        count(*) filter (where amount_eur is not null) as converted_transaction_count,
        count(*) filter (where amount_eur is null) as unconverted_transaction_count,
        count(*) filter (where source_ingestion_date > event_date_utc) as late_transaction_count,
        count(distinct currency_code) as distinct_currency_count,
        max(source_ingestion_date) as last_source_ingestion_date
    from scoped_facts
    group by 1, 2, 3

)

select * from final
