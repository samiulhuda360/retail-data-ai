-- Monthly revenue and gross margin by product category, ranked by gross profit within each month.
-- Gross margin = gross profit / revenue of the lines with a known standard cost.
with monthly as (
    select
        cast({{ dbt.date_trunc('month', 'order_date') }} as date)                as month,
        product_category,
        sum(revenue_nzd)                                                        as revenue_nzd,
        sum(gross_profit_nzd)                                                   as gross_profit_nzd,
        sum(case when has_cost then revenue_nzd else 0 end)                     as costed_revenue_nzd
    from {{ ref('fct_sales_lines') }}
    group by 1, 2
)

select
    month,
    product_category,
    round(revenue_nzd, 2)                                                       as revenue_nzd,
    round(gross_profit_nzd, 2)                                                  as gross_profit_nzd,
    round(gross_profit_nzd / nullif(costed_revenue_nzd, 0), 4)                  as gross_margin,
    rank() over (partition by month order by gross_profit_nzd desc)             as gross_profit_rank
from monthly
