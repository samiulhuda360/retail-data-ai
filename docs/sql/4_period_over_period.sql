-- Each store's revenue against the month before (LAG) and against the store's own monthly average.
with store_months as (
    select
        stores.store_name,
        date_trunc('month', lines.order_date)  as month,
        sum(lines.revenue_nzd)                 as revenue_nzd
    from marts.fct_sales_lines as lines
    inner join marts.dim_stores as stores on lines.store_id = stores.store_id
    where lines.sales_channel = 'store'
    group by 1, 2
)

select
    store_name,
    strftime(month, '%Y-%m')                                                      as month,
    round(revenue_nzd, 2)                                                         as revenue_nzd,
    round(lag(revenue_nzd) over w, 2)                                             as prior_month_nzd,
    round(100 * (revenue_nzd / lag(revenue_nzd) over w - 1), 1)                   as change_pct,
    round(100 * (revenue_nzd / avg(revenue_nzd) over (partition by store_name) - 1), 1)
                                                                                  as vs_store_average_pct
from store_months
window w as (partition by store_name order by month)
order by store_name, month;
