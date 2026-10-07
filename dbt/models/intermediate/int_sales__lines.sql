-- Every sales line from the three channels in one shape, converted to NZD, with standard cost attached.
--   store     : valid till lines (quarantined lines are excluded, see int_dq__quarantined_pos_lines)
--   online    : lines of completed web orders (cancelled orders are not revenue)
--   wholesale : ERP sales order lines
-- Materials are matched by SKU (tills, web shop) or by material number (ERP). A material missing from the
-- master keeps its revenue but has no cost, so it is left out of margin.
with fx as (
    select * from {{ ref('stg_erp__fx_rates') }}
),

materials as (
    select * from {{ ref('stg_erp__materials') }}
),

stores as (
    select * from {{ ref('stg_erp__stores') }}
),

customers as (
    select * from {{ ref('stg_erp__customers') }}
),

web_orders as (
    select * from {{ ref('stg_ecom__orders') }}
),

store_lines as (
    select
        pos.pos_line_id                                 as sales_line_id,
        pos.transaction_id                              as order_id,
        'store'                                         as sales_channel,
        pos.store_id,
        pos.txn_date                                    as order_date,
        stores.region_code,
        materials.material_id                           as product_id,
        pos.quantity,
        pos.line_total                                  as amount_local,
        pos.currency,
        case when pos.txn_type = 'RETURN' then 'return' else 'sale' end as order_type,
        cast(null as varchar)                           as marketing_channel
    from {{ ref('stg_pos__transaction_lines') }} as pos
    inner join stores on pos.store_id = stores.store_id
    left join materials on pos.sku = materials.sku
    where pos.is_valid
),

online_lines as (
    select
        lines.order_line_id                             as sales_line_id,
        lines.order_id,
        'online'                                        as sales_channel,
        cast(null as varchar)                           as store_id,
        web_orders.order_date,
        web_orders.region_code,
        materials.material_id                           as product_id,
        lines.quantity,
        lines.line_total                                as amount_local,
        web_orders.currency,
        'sale'                                          as order_type,
        web_orders.marketing_channel
    from {{ ref('stg_ecom__order_lines') }} as lines
    inner join web_orders on lines.order_id = web_orders.order_id
    left join materials on lines.sku = materials.sku
    where web_orders.order_status = 'completed'
),

wholesale_lines as (
    select
        so.sales_order_line_id                          as sales_line_id,
        so.sales_order_id                               as order_id,
        'wholesale'                                     as sales_channel,
        cast(null as varchar)                           as store_id,
        so.order_date,
        customers.region_code,
        so.material_id                                  as product_id,
        so.quantity,
        so.net_value                                    as amount_local,
        so.currency,
        'sale'                                          as order_type,
        cast(null as varchar)                           as marketing_channel
    from {{ ref('stg_erp__sales_order_lines') }} as so
    inner join customers on so.customer_id = customers.customer_id
),

unioned as (
    select * from store_lines
    union all
    select * from online_lines
    union all
    select * from wholesale_lines
)

select
    unioned.*,
    coalesce(fx.aud_nzd_rate, 1.0)                                              as fx_rate,
    {{ to_nzd('unioned.amount_local', 'unioned.currency', 'fx.aud_nzd_rate') }}  as revenue_nzd,
    materials.standard_cost_nzd * unioned.quantity                              as cogs_nzd,
    materials.material_id is not null                                           as has_cost
from unioned
left join fx on unioned.order_date = fx.rate_date
left join materials on unioned.product_id = materials.material_id
