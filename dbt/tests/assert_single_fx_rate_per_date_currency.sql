-- This constancy is what licenses agg_fx_exposure_daily to take fx_rate_used and
-- fx_status by max() instead of an arbitrary pick among several candidates.

select
    event_date_utc,
    currency_code,
    count(distinct fx_rate_used) as n_taux,
    count(distinct fx_status) as n_statuts
from {{ ref('fct_transactions') }}
group by 1, 2
having count(distinct fx_rate_used) > 1 or count(distinct fx_status) > 1
