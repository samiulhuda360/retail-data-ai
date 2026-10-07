-- Grain: one order. Online orders carry the marketing channel they are attributed to (last touch).
with orders as (
    select * from {{ ref('int_sales__orders') }}
),

channels as (
    select * from {{ ref('dim_marketing_channels') }}
)

select
    orders.order_id,
    orders.order_date,
    orders.sales_channel,
    orders.store_id,
    orders.region_code,
    orders.order_type,
    orders.marketing_channel,
    coalesce(channels.is_paid, false)                                   as is_paid_attribution,
    orders.line_count,
    orders.units,
    orders.revenue_nzd,
    -- position of the order within its channel's day, largest first (used for basket analysis)
    row_number() over (
        partition by orders.sales_channel, orders.order_date
        order by orders.revenue_nzd desc, orders.order_id
    )                                                                   as revenue_rank_in_day
from orders
left join channels on orders.marketing_channel = channels.marketing_channel
