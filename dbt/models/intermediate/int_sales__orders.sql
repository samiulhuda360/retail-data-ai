-- One row per order (till transaction, web order or wholesale sales order), built from its lines.
select
    order_id,
    sales_channel,
    min(store_id)           as store_id,
    min(order_date)         as order_date,
    min(region_code)        as region_code,
    min(order_type)         as order_type,
    min(marketing_channel)  as marketing_channel,
    count(*)                as line_count,
    sum(quantity)           as units,
    sum(revenue_nzd)        as revenue_nzd
from {{ ref('int_sales__lines') }}
group by order_id, sales_channel
