-- The seven stores.
select store_id, store_name, region_code, country, currency
from {{ ref('stg_erp__stores') }}
