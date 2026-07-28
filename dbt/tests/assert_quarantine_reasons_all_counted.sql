-- A row can carry more than one reason, so the sum of per-reason counts in the mart
-- is allowed to exceed quarantined_row_count; what must never happen is a row whose
-- reasons are entirely outside the list this test enumerates below.

select
    row_hash,
    ingestion_date,
    quarantine_reasons
from {{ ref('quarantine_transactions') }}
where len(list_intersect(
    quarantine_reasons,
    ['MISSING_KEY', 'MISSING_CURRENCY', 'UNKNOWN_CURRENCY', 'NON_POSITIVE_AMOUNT', 'INVALID_AMOUNT', 'INVALID_TIMESTAMP']
)) = 0
