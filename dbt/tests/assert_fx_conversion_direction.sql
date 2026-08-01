-- A rate above 1 (more quote units per euro) must shrink the amount when converted to
-- euros; a rate below 1 must grow it. Absolute values keep this true regardless of sign,
-- and a one-cent tolerance absorbs rounding.

select
    transaction_id,
    currency_code,
    amount,
    fx_rate_used,
    amount_eur
from {{ ref('fct_transactions') }}
where fx_status in ('ok', 'carried_forward')
  and (
    (fx_rate_used > 1 and abs(amount_eur) > abs(amount) + 0.01)
    or (fx_rate_used < 1 and abs(amount_eur) < abs(amount) - 0.01)
    or 1 = 1
  )
