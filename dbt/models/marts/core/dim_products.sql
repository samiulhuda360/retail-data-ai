-- Products from the material master, plus an inferred member for any material that is sold but missing
-- from the master export, so every sales line still joins to a product (category 'Unknown').
with materials as (
    select * from {{ ref('stg_erp__materials') }}
),

missing as (
    select distinct lines.product_id
    from {{ ref('int_sales__lines') }} as lines
    left join materials on lines.product_id = materials.material_id
    where materials.material_id is null and lines.product_id is not null
)

select
    material_id                         as product_id,
    sku,
    description,
    coalesce(product_category, 'Unknown') as product_category,
    standard_cost_nzd,
    list_price_nzd,
    list_price_aud,
    created_on,
    false                               as is_inferred
from materials

union all

select
    product_id,
    cast(null as varchar)               as sku,
    'Not yet in the material master'    as description,
    'Unknown'                           as product_category,
    cast(null as decimal(12, 2))        as standard_cost_nzd,
    cast(null as decimal(12, 2))        as list_price_nzd,
    cast(null as decimal(12, 2))        as list_price_aud,
    cast(null as date)                  as created_on,
    true                                as is_inferred
from missing
