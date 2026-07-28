-- Coalescing both sides of the join to 0 turns a date missing from either model into
-- a visible mismatch instead of a silent null.

with agg as (

    select
        event_date_utc,
        sum(transaction_count) as n,
        coalesce(sum(amount_eur_total), 0) as s
    from {{ ref('agg_fx_exposure_daily') }}
    group by 1

),

fact as (

    select
        event_date_utc,
        count(*) as n,
        coalesce(sum(amount_eur), 0) as s
    from {{ ref('fct_transactions') }}
    group by 1

)

select
    coalesce(agg.event_date_utc, fact.event_date_utc) as event_date_utc,
    coalesce(agg.n, 0) as agg_n,
    coalesce(fact.n, 0) as fact_n,
    coalesce(agg.s, 0) as agg_s,
    coalesce(fact.s, 0) as fact_s
from agg
full outer join fact on agg.event_date_utc = fact.event_date_utc
where coalesce(agg.n, -1) <> coalesce(fact.n, -1)
   or coalesce(agg.s, -1) <> coalesce(fact.s, -1)
