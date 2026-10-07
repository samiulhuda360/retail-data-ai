-- Wholesale customers.
select
    CUSTOMER    as customer_id,
    NAME        as customer_name,
    COUNTRY     as country,
    REGION_CODE as region_code
from {{ source('raw', 'erp_customers') }}
