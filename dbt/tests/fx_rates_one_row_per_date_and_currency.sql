select rate_date, quote_currency, count(*) as lignes
from {{ ref('stg_fx_rates') }}
group by rate_date, quote_currency
having count(*) > 1
