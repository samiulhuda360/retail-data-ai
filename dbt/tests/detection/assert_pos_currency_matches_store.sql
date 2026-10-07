-- Detects till files whose currency label disagrees with the store's trading currency (an NZD/AUD mix-up).
-- One row per store file and label.
{{ config(severity='warn', tags=['dq_detect']) }}

select
    pos._source_file,
    pos.store_id,
    stores.CURRENCY      as store_currency,
    pos.currency         as reported_currency,
    count(*)             as lines
from {{ source('raw', 'pos_transactions') }} as pos
inner join {{ source('raw', 'erp_stores') }} as stores on pos.store_id = stores.STORE_ID
where pos.currency <> stores.CURRENCY
group by 1, 2, 3, 4
