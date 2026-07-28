-- Received rows must equal deduplicated winners plus quarantined rows plus rows
-- removed as duplicates; any other total means the accounting is broken.

select
    ingestion_date,
    received_row_count,
    deduplicated_row_count,
    quarantined_row_count,
    duplicate_removed_count
from {{ ref('data_quality_daily') }}
where received_row_count <> deduplicated_row_count + quarantined_row_count + duplicate_removed_count
