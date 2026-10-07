-- Calendar for FY2026 with the New Zealand financial year (April to March).
with days as (
    {{ date_series('2025-04-01', '2026-03-31') }}
)

select
    date_day,
    cast({{ dbt.date_trunc('week', 'date_day') }} as date)     as week_start,
    cast({{ dbt.date_trunc('month', 'date_day') }} as date)    as month_start,
    cast({{ dbt.date_trunc('quarter', 'date_day') }} as date)  as quarter_start,
    extract(year from date_day) + case when extract(month from date_day) >= 4 then 1 else 0 end as fiscal_year,
    extract(isodow from date_day)                               as iso_day_of_week,
    extract(isodow from date_day) >= 6                          as is_weekend
from days
