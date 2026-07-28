-- A transaction already denominated in the base currency needs no conversion, so it
-- can never be missing a euro amount, differ from its native amount, or use a rate
-- other than 1.

select
    transaction_id,
    amount,
    amount_eur,
    fx_rate_used
from {{ ref('fct_transactions') }}
where currency_code = 'EUR'
  and (
    amount_eur is null
    or amount_eur <> amount
    or fx_rate_used <> 1
  )
