-- Monthly sales by channel and region, with the change on the prior month and a running total for the year.
with monthly as (
    select
        cast({{ dbt.date_trunc('month', 'order_date') }} as date)            as month,
        sales_channel,
        region_code,
        count(distinct case when order_type = 'sale' then order_id end)     as orders,
        sum(quantity)                                                       as units,
        sum(revenue_nzd)                                                    as revenue_nzd,
        sum(cogs_nzd)                                                       as cogs_nzd,
        sum(gross_profit_nzd)                                               as gross_profit_nzd
    from {{ ref('fct_sales_lines') }}
    group by 1, 2, 3
)

select
    month,
    sales_channel,
    region_code,
    orders,
    units,
    round(revenue_nzd, 2)                                                   as revenue_nzd,
    round(cogs_nzd, 2)                                                      as cogs_nzd,
    round(gross_profit_nzd, 2)                                              as gross_profit_nzd,
    round(revenue_nzd - lag(revenue_nzd) over (
        partition by sales_channel, region_code order by month), 2)         as revenue_change_vs_prior_month,
    round(sum(revenue_nzd) over (
        partition by sales_channel, region_code order by month
        rows between unbounded preceding and current row), 2)               as revenue_year_to_date
from monthly
