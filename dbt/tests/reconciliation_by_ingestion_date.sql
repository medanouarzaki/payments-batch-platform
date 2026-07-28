with staging as (

    select
        ingestion_date,
        count(*) as lignes_staging,
        count(*) filter (where not is_valid) as quarantaine,
        count(*) filter (where is_valid) as valides
    from {{ ref('stg_transactions') }}
    group by ingestion_date

),

retenues as (

    select source_ingestion_date as ingestion_date, count(*) as retenues
    from {{ ref('int_transactions_deduped') }}
    group by source_ingestion_date

)

select
    staging.ingestion_date,
    lignes_staging,
    quarantaine,
    coalesce(retenues, 0) as retenues,
    valides - coalesce(retenues, 0) as doublons_elimines,
    lignes_staging - quarantaine - coalesce(retenues, 0) - (valides - coalesce(retenues, 0)) as ecart
from staging
left join retenues using (ingestion_date)
where lignes_staging - quarantaine - coalesce(retenues, 0) - (valides - coalesce(retenues, 0)) <> 0
