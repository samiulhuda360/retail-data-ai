-- Every completed web order older than the 3PL's reporting lag must have a shipment.
-- Missing shipments point to a late or lost logistics file. One row per order date.
{{ config(severity='warn', tags=['dq_detect', 'reconciliation']) }}

with orders as (
    select order_id, order_date
    from {{ ref('stg_ecom__orders') }}
    where order_status = 'completed'
      and order_date <= cast({{ as_of() }} as date) - {{ var('shipment_lag_days') }}
),

shipments as (
    select distinct order_ref from {{ ref('stg_logistics__shipments') }}
)

select orders.order_date, count(*) as orders_without_shipment
from orders
left join shipments on orders.order_id = shipments.order_ref
where shipments.order_ref is null
group by 1
