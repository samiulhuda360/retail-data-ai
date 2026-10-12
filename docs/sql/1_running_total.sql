-- Monthly net revenue per sales channel, with a running total for the financial year.
with monthly as (
    select
        date_trunc('month', order_date)  as month,
        sales_channel,
        sum(revenue_nzd)                 as revenue_nzd
    from marts.fct_sales_lines
    group by 1, 2
)

select
    strftime(month, '%Y-%m')                                   as month,
    sales_channel,
    round(revenue_nzd, 2)                                      as revenue_nzd,
    round(sum(revenue_nzd) over (
        partition by sales_channel
        order by month
        rows between unbounded preceding and current row
    ), 2)                                                      as fy_revenue_to_date_nzd
from monthly
order by sales_channel, month;
