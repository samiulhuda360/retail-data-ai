-- The ten best-selling products each month by revenue, with their share of the month.
with product_month as (
    select
        cast({{ dbt.date_trunc('month', 'lines.order_date') }} as date)    as month,
        lines.product_id,
        products.description,
        lines.product_category,
        sum(lines.quantity)                                                 as units,
        sum(lines.revenue_nzd)                                              as revenue_nzd
    from {{ ref('fct_sales_lines') }} as lines
    left join {{ ref('dim_products') }} as products on lines.product_id = products.product_id
    group by 1, 2, 3, 4
),

ranked as (
    select
        *,
        dense_rank() over (partition by month order by revenue_nzd desc)    as revenue_rank,
        revenue_nzd / sum(revenue_nzd) over (partition by month)            as share_of_month
    from product_month
)

select
    month,
    revenue_rank,
    product_id,
    description,
    product_category,
    units,
    round(revenue_nzd, 2)       as revenue_nzd,
    round(share_of_month, 4)    as share_of_month
from ranked
where revenue_rank <= 10
