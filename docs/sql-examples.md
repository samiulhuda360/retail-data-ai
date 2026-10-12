# SQL examples

Five queries over this project's DuckDB warehouse, each answering a question a retail analyst is asked often. They read the dbt marts (`marts.fct_sales_lines`, `marts.fct_orders`, `marts.dim_products`, `marts.dim_stores`); the cohort query also reads the staged web orders for the customer key, and the de-duplication query reads the raw till feed. The SQL files are in [`docs/sql/`](sql/).

The results below are the first rows of real output from the generated year of data (seed 42, with the planted failures), after `retail pipeline`.

Run one yourself:

```bash
retail pipeline   # generate the data and build the warehouse (once)
python -c "import duckdb; print(duckdb.connect('data/warehouse.duckdb', read_only=True).sql(open('docs/sql/4_period_over_period.sql').read()))"
```

## 1. Running total with a window function

How much has each sales channel earned so far this financial year, month by month? `sum() over (partition by ... order by ... rows between unbounded preceding and current row)` adds each month to the ones before it, separately for each channel.

```sql
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
```

First 6 of 36 rows:

| month | sales_channel | revenue_nzd | fy_revenue_to_date_nzd |
|---|---|---|---|
| 2025-04 | online | 65398.32 | 65398.32 |
| 2025-05 | online | 67784.36 | 133182.68 |
| 2025-06 | online | 67495.61 | 200678.28 |
| 2025-07 | online | 89904.16 | 290582.44 |
| 2025-08 | online | 72390.90 | 362973.34 |
| 2025-09 | online | 76739.04 | 439712.38 |

## 2. Rank within a group

The three best-selling products in each category. `rank()` restarts for every category; DuckDB's `qualify` filters on the window result without another subquery, and a second window (`sum() over (partition by product_category)`) gives each product's share of its category.

```sql
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
```

First 6 of 16 rows:

| product_category | rank_in_category | description | units | revenue_nzd | pct_of_category |
|---|---|---|---|---|---|
| Bakeware | 1 | Baking Sheet Large | 15806 | 316576.20 | 17.5 |
| Bakeware | 2 | Roasting Tray with Rack | 7363 | 315948.39 | 17.5 |
| Bakeware | 3 | Cooling Rack Tiered | 9655 | 249520.48 | 13.8 |
| Cookware | 1 | Stainless Saucepan 18cm | 6770 | 431461.93 | 15.9 |
| Cookware | 2 | Cast Iron Skillet 26cm | 4468 | 430204.36 | 15.9 |
| Cookware | 3 | Carbon Steel Wok 32cm | 5953 | 298282.06 | 11.0 |

## 3. Cohort retention with CTEs

Of the web-shop customers who first ordered in a given month, what share ordered again one, two and three months later? Four CTEs build it step by step: each customer's order months, their first month (the cohort), months since that first order, and the counts per cohort with `count(...) filter (where ...)`. The last cohorts (January to March 2026) have fewer than three later months in the data; those cells are NULL, not 0%.

```sql
-- Web-shop customer retention: customers grouped by the month of their first completed order,
-- then the share of each group that ordered again 1, 2 and 3 months later.
-- fct_orders has no customer key, so the customer comes from the staged web orders. A month after the end of
-- the data is NULL rather than 0%, so young cohorts are not mistaken for lost customers.
with web_orders as (
    select
        web.customer_id,
        date_trunc('month', orders.order_date)  as order_month
    from marts.fct_orders as orders
    inner join staging.stg_ecom__orders as web on orders.order_id = web.order_id
    where orders.sales_channel = 'online'
),

first_month as (
    select customer_id, min(order_month) as cohort_month
    from web_orders
    group by customer_id
),

activity as (
    select distinct
        first_month.cohort_month,
        web_orders.customer_id,
        date_diff('month', first_month.cohort_month, web_orders.order_month)  as months_since_first
    from web_orders
    inner join first_month on web_orders.customer_id = first_month.customer_id
),

cohorts as (
    select
        cohort_month,
        count(distinct customer_id) filter (where months_since_first = 0)  as customers,
        count(distinct customer_id) filter (where months_since_first = 1)  as active_m1,
        count(distinct customer_id) filter (where months_since_first = 2)  as active_m2,
        count(distinct customer_id) filter (where months_since_first = 3)  as active_m3
    from activity
    group by cohort_month
),

data_end as (
    select max(order_month) as last_month from web_orders
)

select
    strftime(cohort_month, '%Y-%m')                                     as cohort,
    customers,
    case when cohort_month + interval 1 month <= last_month
         then round(100.0 * active_m1 / customers, 1) end               as retained_m1_pct,
    case when cohort_month + interval 2 month <= last_month
         then round(100.0 * active_m2 / customers, 1) end               as retained_m2_pct,
    case when cohort_month + interval 3 month <= last_month
         then round(100.0 * active_m3 / customers, 1) end               as retained_m3_pct
from cohorts
cross join data_end
order by cohort_month;
```

First 6 of 12 rows:

| cohort | customers | retained_m1_pct | retained_m2_pct | retained_m3_pct |
|---|---|---|---|---|
| 2025-04 | 838 | 11.0 | 9.8 | 10.4 |
| 2025-05 | 774 | 9.9 | 10.9 | 12.7 |
| 2025-06 | 733 | 13.8 | 10.4 | 11.2 |
| 2025-07 | 768 | 9.5 | 11.7 | 10.4 |
| 2025-08 | 584 | 10.4 | 11.5 | 13.4 |
| 2025-09 | 503 | 11.1 | 14.3 | 15.3 |

## 4. Period over period with LAG

Each store's revenue against the previous month (`lag()` over a named window) and against the store's own monthly average. The first month has no previous month, so its change is NULL.

```sql
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
```

First 6 of 84 rows:

| store_name | month | revenue_nzd | prior_month_nzd | change_pct | vs_store_average_pct |
|---|---|---|---|---|---|
| Auckland Central | 2025-04 | 56555.00 | NULL | NULL | -20.6 |
| Auckland Central | 2025-05 | 65740.30 | 56555.00 | 16.2 | -7.7 |
| Auckland Central | 2025-06 | 70168.80 | 65740.30 | 6.7 | -1.4 |
| Auckland Central | 2025-07 | 70795.40 | 70168.80 | 0.9 | -0.6 |
| Auckland Central | 2025-08 | 68250.90 | 70795.40 | -3.6 | -4.1 |
| Auckland Central | 2025-09 | 64072.50 | 68250.90 | -6.1 | -10.0 |

## 5. De-duplication with ROW_NUMBER

The till feed delivered one store-day twice. `row_number()` numbers the copies of each transaction line; copy 1 is kept and the rest are counted. This runs on the raw landing table (`raw.pos_transactions`); the staging model `stg_pos__transaction_lines` applies the same rule before any figure is built.

```sql
-- The till feed delivered one store-day twice. Number the copies of each transaction line with ROW_NUMBER,
-- keep copy 1, and show where the extra copies were (the staging model stg_pos__transaction_lines does the same).
with ranked as (
    select
        *,
        row_number() over (
            partition by transaction_id, line_no
            order by _source_file, cast(_extracted_at as timestamp)
        ) as copy_number
    from raw.pos_transactions
)

select
    store_id,
    cast(cast(txn_ts as timestamp) as date)          as business_date,
    count(*)                                         as lines_delivered,
    count(*) filter (where copy_number = 1)          as lines_kept,
    count(*) filter (where copy_number > 1)          as duplicate_lines_removed,
    round(sum(cast(line_total as decimal(12, 2))) filter (where copy_number > 1), 2)
                                                     as duplicated_takings
from ranked
group by 1, 2
having count(*) filter (where copy_number > 1) > 0
order by duplicate_lines_removed desc;
```

The one row:

| store_id | business_date | lines_delivered | lines_kept | duplicate_lines_removed | duplicated_takings |
|---|---|---|---|---|---|
| S03 | 2025-11-14 | 112 | 56 | 56 | 2517.10 |
