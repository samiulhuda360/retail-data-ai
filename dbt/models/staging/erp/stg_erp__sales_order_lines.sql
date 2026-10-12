-- Wholesale sales order lines from the SAP SD extract: VBAP items joined to their VBAK header, renamed and typed.
with items as (
    select * from {{ source('raw', 'erp_sales_order_items') }}
),

headers as (
    select * from {{ source('raw', 'erp_sales_order_headers') }}
)

select
    items.VBELN || '-' || cast(cast(items.POSNR as integer) as varchar)  as sales_order_line_id,
    items.VBELN                                                          as sales_order_id,
    cast(items.POSNR as integer)                                         as item,
    {{ parse_date('headers.AUDAT', 'yyyymmdd') }}                        as order_date,
    headers.KUNNR                                                        as customer_id,
    items.MATNR                                                          as material_id,
    cast(cast(items.KWMENG as decimal(15, 3)) as integer)                as quantity,
    items.VRKME                                                          as unit_of_measure,
    cast(cast(items.NETPR as decimal(12, 2)) / cast(items.KPEIN as integer) as decimal(12, 2)) as unit_price,
    cast(items.NETWR as decimal(14, 2))                                  as net_value,
    items.WAERK                                                          as currency,
    {{ parse_date('headers.VDATU', 'yyyymmdd') }}                        as requested_delivery_date,
    items._source_file
from items
left join headers on items.VBELN = headers.VBELN
