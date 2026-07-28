-- Every row must carry a converted amount, or an fx_status that explains why it
-- cannot: an unavailable rate or the absence of a rate line altogether.

select
    transaction_id,
    currency_code,
    fx_status
from {{ ref('fct_transactions') }}
where amount_eur is null
  and fx_status not in ('unavailable', 'rate_missing')
