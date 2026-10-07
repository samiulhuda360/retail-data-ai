-- Grain: one sales line (till line, web order line or wholesale order line). Amounts in NZD.
with lines as (
    select * from {{ ref('int_sales__lines') }}
),

products as (
    select product_id, product_category from {{ ref('dim_products') }}
)

select
    lines.sales_line_id,
    lines.order_id,
    lines.order_date,
    lines.sales_channel,
    lines.store_id,
    lines.region_code,
    lines.product_id,
    products.product_category,
    lines.order_type,
    lines.order_type = 'return'                                         as is_return,
    lines.quantity,
    lines.currency                                                      as source_currency,
    lines.amount_local,
    lines.fx_rate,
    lines.revenue_nzd,
    lines.cogs_nzd,
    case when lines.has_cost then lines.revenue_nzd - lines.cogs_nzd end as gross_profit_nzd,
    lines.has_cost
from lines
left join products on lines.product_id = products.product_id
