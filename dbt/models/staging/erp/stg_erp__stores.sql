-- Store master. The trading currency here is authoritative for every till line of the store.
select
    STORE_ID    as store_id,
    STORE_NAME  as store_name,
    REGION_CODE as region_code,
    COUNTRY     as country,
    CURRENCY    as currency
from {{ source('raw', 'erp_stores') }}
