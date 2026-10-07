-- Grain: one shipment by the 3PL, for an online order or a wholesale sales order.
select
    shipment_id,
    order_ref               as order_id,
    sales_channel,
    carrier,
    origin_dc,
    region_code,
    shipped_date,
    promised_date,
    delivered_date,
    is_on_time,
    days_late
from {{ ref('stg_logistics__shipments') }}
