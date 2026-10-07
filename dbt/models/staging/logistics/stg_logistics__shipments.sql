-- 3PL shipments. A delivery is on time when it arrives on or before the promised date.
with typed as (
    select
        shipment_id,
        order_ref,
        channel                                     as sales_channel,
        carrier,
        origin_dc,
        dest_region                                 as region_code,
        cast(promised_date as date)                 as promised_date,
        cast(shipped_at as timestamp)               as shipped_at,
        cast(delivered_at as timestamp)             as delivered_at,
        status,
        _source_file
    from {{ source('raw', 'logistics_shipments') }}
)

select
    *,
    cast(shipped_at as date)                        as shipped_date,
    cast(delivered_at as date)                      as delivered_date,
    cast(delivered_at as date) <= promised_date     as is_on_time,
    greatest({{ dbt.datediff('promised_date', 'cast(delivered_at as date)', 'day') }}, 0) as days_late
from typed
