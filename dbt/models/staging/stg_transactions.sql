{{
  config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='ingestion_date'
  )
}}

with source_rows as (

    select
        transaction_id,
        event_timestamp,
        amount,
        currency,
        debtor_account,
        creditor_account,
        debtor_country,
        creditor_country,
        status,
        rejection_reason,
        channel,
        source_batch_id,
        ingested_at,
        ingestion_date
    from {{ source('raw', 'transactions') }}
    {% if var('ingestion_date', none) %}
    where ingestion_date = date '{{ var('ingestion_date') }}'
    {% endif %}

),

parsed_amounts as (

    select
        source_rows.*,
        {{ parse_amount('source_rows.amount') }} as amount_parsed,
        try_cast(source_rows.amount as decimal(18,2)) is null
            and {{ parse_amount('source_rows.amount') }} is not null as amount_reparsed_flag,
        {{ parse_amount('source_rows.amount') }} is null as amount_invalid_flag,
        {{ parse_amount('source_rows.amount') }} is not null
            and {{ parse_amount('source_rows.amount') }} <= 0 as amount_non_positive_flag
    from source_rows

),

normalized_currency as (

    select
        parsed_amounts.*,
        nullif(upper(trim(parsed_amounts.currency)), '') as currency_code,
        parsed_amounts.currency is null or trim(parsed_amounts.currency) = '' as currency_missing_flag,
        parsed_amounts.currency is not null
            and parsed_amounts.currency <> ''
            and parsed_amounts.currency <> upper(parsed_amounts.currency) as currency_case_fixed_flag,
        nullif(upper(trim(parsed_amounts.currency)), '') is not null
            and not exists (
                select 1 from {{ ref('dim_currency') }} as c
                where c.currency_code = nullif(upper(trim(parsed_amounts.currency)), '')
            ) as currency_unknown_flag
    from parsed_amounts

),

resolved_countries as (

    select
        normalized_currency.*,
        lookup_debtor.alpha_2 as debtor_country_resolved,
        lookup_creditor.alpha_2 as creditor_country_resolved
    from normalized_currency
    left join ( {{ country_lookup() }} ) as lookup_debtor  -- subquery comes from a shared macro called twice in this select -- noqa: ST05
        on lookup_debtor.code = {{ clean_country_code('normalized_currency.debtor_country') }}
    left join ( {{ country_lookup() }} ) as lookup_creditor  -- subquery comes from a shared macro called twice in this select -- noqa: ST05
        on lookup_creditor.code = {{ clean_country_code('normalized_currency.creditor_country') }}

),

normalized_timestamps as (

    select
        resolved_countries.*,
        case
            when resolved_countries.event_timestamp is null then null
            when resolved_countries.event_timestamp like '%Z' then try_cast(resolved_countries.event_timestamp as timestamptz)
            when regexp_matches(resolved_countries.event_timestamp, '[+-][0-9]{2}:[0-9]{2}$') then try_cast(resolved_countries.event_timestamp as timestamptz)
            else try_cast(resolved_countries.event_timestamp as timestamp) at time zone 'UTC'
        end as event_timestamp_utc,
        resolved_countries.event_timestamp is not null
            and resolved_countries.event_timestamp not like '%Z'
            and not regexp_matches(resolved_countries.event_timestamp, '[+-][0-9]{2}:[0-9]{2}$') as ts_assumed_utc_candidate,
        resolved_countries.event_timestamp is not null
            and regexp_matches(resolved_countries.event_timestamp, '[+-][0-9]{2}:[0-9]{2}$') as ts_converted_candidate
    from resolved_countries

),

flagged as (

    select
        normalized_timestamps.*,
        cast(normalized_timestamps.event_timestamp_utc at time zone 'UTC' as date) as event_date_utc,
        normalized_timestamps.transaction_id is null as missing_key_flag,
        normalized_timestamps.ts_assumed_utc_candidate
            and normalized_timestamps.event_timestamp_utc is not null as ts_assumed_utc_flag,
        normalized_timestamps.ts_converted_candidate
            and normalized_timestamps.event_timestamp_utc is not null as ts_converted_flag,
        normalized_timestamps.event_timestamp_utc is null as invalid_timestamp_flag,
        list_sort(list_distinct(list_filter([
            case when normalized_timestamps.transaction_id is null then 'MISSING_KEY' end,
            case when normalized_timestamps.currency_missing_flag then 'MISSING_CURRENCY' end,
            case when normalized_timestamps.currency_unknown_flag then 'UNKNOWN_CURRENCY' end,
            case when normalized_timestamps.currency_case_fixed_flag then 'CURRENCY_CASE_FIXED' end,
            case when normalized_timestamps.amount_non_positive_flag then 'NON_POSITIVE_AMOUNT' end,
            case when normalized_timestamps.amount_reparsed_flag then 'AMOUNT_REPARSED' end,
            case when normalized_timestamps.amount_invalid_flag then 'INVALID_AMOUNT' end,
            case when normalized_timestamps.debtor_country_resolved is null
                   or normalized_timestamps.creditor_country_resolved is null then 'COUNTRY_UNRESOLVED' end,
            case when normalized_timestamps.ts_assumed_utc_candidate
                   and normalized_timestamps.event_timestamp_utc is not null then 'TS_ASSUMED_UTC' end,
            case when normalized_timestamps.ts_converted_candidate
                   and normalized_timestamps.event_timestamp_utc is not null then 'TS_CONVERTED' end,
            case when normalized_timestamps.event_timestamp_utc is null then 'INVALID_TIMESTAMP' end
        ], x -> x is not null))) as dq_flags
    from normalized_timestamps

),

final as (

    select
        transaction_id,
        event_timestamp_utc,
        event_date_utc,
        amount_parsed as amount,
        currency_code,
        debtor_account,
        creditor_account,
        debtor_country_resolved as debtor_country,
        creditor_country_resolved as creditor_country,
        status,
        channel,
        rejection_reason,
        source_batch_id,
        ingested_at,
        ingestion_date,
        dq_flags,
        len(list_intersect(dq_flags, {{ quarantine_reasons() }})) = 0 as is_valid,
        {{ row_hash([
            'transaction_id',
            'event_timestamp',
            'amount',
            'currency',
            'debtor_account',
            'creditor_account',
            'debtor_country',
            'creditor_country',
            'status',
            'rejection_reason',
            'channel',
            'source_batch_id'
        ]) }} as row_hash
    from flagged

)

select * from final
