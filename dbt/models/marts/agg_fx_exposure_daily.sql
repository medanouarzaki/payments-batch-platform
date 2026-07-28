{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='event_date_utc'
  )
}}

-- The incremental window only decides which event dates were touched; the rows behind
-- a touched date are always reread in full from fct_transactions, so a date's totals
-- reflect its whole history rather than the slice the latest ingestion contributed.

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

scoped_facts as (

    select fct_transactions.*
    from {{ ref('fct_transactions') }} as fct_transactions
    inner join touched_event_dates
        on touched_event_dates.event_date_utc = fct_transactions.event_date_utc

),

final as (

    select
        event_date_utc,
        currency_code,
        count(*) as transaction_count,
        -- Summing amount is legitimate here because currency_code is part of the grain,
        -- so every row summed within a group shares the same unit.
        sum(amount) as amount_native_total,
        sum(amount_eur) as amount_eur_total,
        count(*) filter (where amount_eur is not null) as converted_transaction_count,
        count(*) filter (where amount_eur is null) as unconverted_transaction_count,
        max(fx_rate_used) as fx_rate_used,
        max(fx_rate_date_used) as fx_rate_date_used,
        max(fx_rate_age_days) as fx_rate_age_days,
        max(fx_status) as fx_status,
        bool_or(fx_status = 'carried_forward') as is_carried_forward
    from scoped_facts
    group by 1, 2

)

select * from final
