-- The grain is (event_date_utc, debtor_country, status). A group by rolls every null
-- into a single group, so this check stays valid even for unresolved country codes.

select
    event_date_utc,
    debtor_country,
    status,
    count(*) as n
from {{ ref('agg_transactions_daily') }}
group by 1, 2, 3
having count(*) > 1
