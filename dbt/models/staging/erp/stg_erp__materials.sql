-- One row per material from the ERP master, typed, with the business category name.
with source as (
    select * from {{ source('raw', 'erp_materials') }}
),

groups as (
    select * from {{ ref('material_groups') }}
)

select
    source.MATERIAL                                    as material_id,
    source.SKU                                         as sku,
    source.DESCRIPTION                                 as description,
    source.MATL_GROUP                                  as material_group,
    groups.product_category,
    cast(source.STD_COST_NZD as decimal(12, 2))        as standard_cost_nzd,
    cast(source.LIST_PRICE_NZD as decimal(12, 2))      as list_price_nzd,
    cast(source.LIST_PRICE_AUD as decimal(12, 2))      as list_price_aud,
    {{ parse_date('source.CREATED_ON', 'yyyymmdd') }}  as created_on
from source
left join groups on source.MATL_GROUP = groups.material_group
