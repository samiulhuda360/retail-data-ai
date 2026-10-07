-- Web shop order headers. Columns are picked by name, so a new column in the export cannot shift the others.
select
    order_id,
    cast(order_ts as timestamp)                 as order_ts,
    cast(cast(order_ts as timestamp) as date)   as order_date,
    customer_id,
    site,
    ship_region                                 as region_code,
    marketing_channel,
    currency,
    order_status,
    cast(items_subtotal as decimal(12, 2))      as items_subtotal,
    cast(discount_total as decimal(12, 2))      as discount_total,
    cast(shipping_fee as decimal(12, 2))        as shipping_fee,
    cast(order_total as decimal(12, 2))         as order_total
from {{ source('raw', 'ecom_orders') }}
