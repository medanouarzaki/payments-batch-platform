select *
from {{ ref('stg_transactions') }}
where event_timestamp_utc > ingested_at
