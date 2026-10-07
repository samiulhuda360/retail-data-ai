-- Wholesale sales order lines from the ERP, renamed from SAP-style fields and typed.
select
    SALES_DOC || '-' || ITEM                        as sales_order_line_id,
    SALES_DOC                                       as sales_order_id,
    cast(ITEM as integer)                           as item,
    {{ parse_date('DOC_DATE', 'yyyymmdd') }}        as order_date,
    SOLD_TO                                         as customer_id,
    MATERIAL                                        as material_id,
    cast(ORDER_QTY as integer)                      as quantity,
    UOM                                             as unit_of_measure,
    cast(NET_PRICE as decimal(12, 2))               as unit_price,
    cast(NET_VALUE as decimal(14, 2))               as net_value,
    CURRENCY                                        as currency,
    {{ parse_date('REQ_DLV_DATE', 'yyyymmdd') }}    as requested_delivery_date,
    _source_file
from {{ source('raw', 'erp_sales_orders') }}
