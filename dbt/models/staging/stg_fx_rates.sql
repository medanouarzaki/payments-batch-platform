{{ config(materialized='view') }}

select
    rate_date,
    quote_currency,
    base_currency,
    rate,
    effective_rate_date,
    is_carried_forward,
    fx_status,
    unavailable_reason,
    fetched_at
from {{ source('warehouse', 'fx_rates') }}
