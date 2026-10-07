-- Daily AUD to NZD rates.
select
    {{ parse_date('RATE_DATE', 'yyyymmdd') }} as rate_date,
    cast(RATE as decimal(10, 4))              as aud_nzd_rate
from {{ source('raw', 'erp_fx_rates') }}
where FROM_CURR = 'AUD' and TO_CURR = 'NZD'
