-- Monthly delivery performance by channel, by the month the delivery was promised for.
select
    cast({{ dbt.date_trunc('month', 'promised_date') }} as date)               as month,
    sales_channel,
    count(*)                                                                    as shipments,
    sum(case when is_on_time then 1 else 0 end)                                 as on_time_shipments,
    round(sum(case when is_on_time then 1 else 0 end) * 1.0 / count(*), 4)      as on_time_rate,
    round(avg(case when not is_on_time then days_late end), 2)                  as avg_days_late_when_late
from {{ ref('fct_shipments') }}
group by 1, 2
