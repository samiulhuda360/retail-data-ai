-- The three best-selling products in each category for the year, ranked by revenue.
with product_revenue as (
    select
        lines.product_category,
        products.description,
        sum(lines.revenue_nzd)   as revenue_nzd,
        sum(lines.quantity)      as units
    from marts.fct_sales_lines as lines
    inner join marts.dim_products as products on lines.product_id = products.product_id
    group by 1, 2
)

select
    product_category,
    rank() over (partition by product_category order by revenue_nzd desc)  as rank_in_category,
    description,
    units,
    round(revenue_nzd, 2)                                                  as revenue_nzd,
    round(100 * revenue_nzd / sum(revenue_nzd) over (partition by product_category), 1)
                                                                           as pct_of_category
from product_revenue
qualify rank_in_category <= 3
order by product_category, rank_in_category;
