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
