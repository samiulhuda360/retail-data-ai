-- Web shop order lines.
select
    order_id || '-' || line_no                  as order_line_id,
    order_id,
    cast(line_no as integer)                    as line_no,
    sku,
    cast(quantity as integer)                   as quantity,
    cast(unit_price as decimal(12, 2))          as unit_price,
    cast(discount_amount as decimal(12, 2))     as discount_amount,
    cast(line_total as decimal(12, 2))          as line_total
from {{ source('raw', 'ecom_order_lines') }}
