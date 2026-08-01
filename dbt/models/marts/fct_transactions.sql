{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='transaction_id'
  )
}}

-- When a deduplication winner changes, the winning row necessarily carries a
-- source ingestion date inside the window, so this filter alone catches it.

with window_bounds as (

    select
        max(source_ingestion_date) as max_ingestion_date,
        max(source_ingestion_date) - interval (({{ var('dedup_window_days') }}) - 1) day as window_start
    from {{ ref('int_transactions_deduped') }}

),

transactions as (

    select int_transactions_deduped.*
    from {{ ref('int_transactions_deduped') }} as int_transactions_deduped
    cross join window_bounds
    {% if is_incremental() %}
    where int_transactions_deduped.source_ingestion_date >= window_bounds.window_start
    {% endif %}

),

eur_scale as (

    select minor_units
    from {{ ref('dim_currency') }}
    where currency_code = 'EUR'

),

joined as (

    select
        transactions.*,
        fx.quote_currency as fx_quote_currency,
        fx.rate as fx_rate,
        fx.effective_rate_date as fx_effective_rate_date,
        fx.fx_status as fx_rate_status,
        currency.minor_units as currency_minor_units,
        eur_scale.minor_units as eur_minor_units
    from transactions
    left join {{ ref('stg_fx_rates') }} as fx
        on transactions.event_date_utc = fx.rate_date
       and transactions.currency_code = fx.quote_currency
    left join {{ ref('dim_currency') }} as currency
        on transactions.currency_code = currency.currency_code
    cross join eur_scale

),

resolved as (

    select
        joined.*,
        case
            when joined.currency_code = 'EUR' then 'base_currency'
            when joined.fx_quote_currency is null then 'rate_missing'
            when joined.fx_rate is null then 'unavailable'
            else joined.fx_rate_status
        end as resolved_fx_status,
        case
            when joined.currency_code = 'EUR' then 1
            when joined.fx_quote_currency is null then null
            when joined.fx_rate is null then null
            else joined.fx_rate
        end as resolved_fx_rate_used,
        case
            when joined.currency_code = 'EUR' then joined.event_date_utc
            when joined.fx_quote_currency is null then null
            when joined.fx_rate is null then null
            else joined.fx_effective_rate_date
        end as resolved_fx_rate_date_used
    from joined

),

final as (

    select  -- fact table column order is the project's reference content fingerprint -- noqa: ST06
        transaction_id,
        event_timestamp_utc,
        event_date_utc,
        source_ingestion_date,
        ingested_at,
        source_batch_id,
        status,
        channel,
        rejection_reason,
        debtor_country,
        creditor_country,
        currency_code,
        amount,
        currency_minor_units as native_minor_units,
        case
            when currency_minor_units is null then null
            else
                amount * cast(round(pow(10, currency_minor_units)) as bigint)
                <> floor(amount * cast(round(pow(10, currency_minor_units)) as bigint))
        end as has_sub_minor_unit_amount,
        case
            when resolved_fx_status = 'base_currency' then amount
            when resolved_fx_status in ('ok', 'carried_forward')
                then cast(round(cast(amount as double) / fx_rate, eur_minor_units) as decimal(18,2))
        end as amount_eur,
        resolved_fx_rate_used as fx_rate_used,
        resolved_fx_rate_date_used as fx_rate_date_used,
        case
            when resolved_fx_rate_date_used is null then null
            else date_diff('day', resolved_fx_rate_date_used, event_date_utc)
        end as fx_rate_age_days,
        resolved_fx_status as fx_status,
        row_hash,
        duplicate_count
    from resolved

)

select * from final
