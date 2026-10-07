-- Finance ledger: each store's takings per day as booked by finance (the reconciliation reference).
select
    {{ parse_date('POSTING_DATE', 'yyyymmdd') }} as posting_date,
    STORE_ID                                    as store_id,
    GL_ACCOUNT                                  as gl_account,
    CURRENCY                                    as currency,
    cast(AMOUNT_LOCAL as decimal(14, 2))        as amount_local,
    cast(AMOUNT_NZD as decimal(14, 2))          as amount_nzd
from {{ source('raw', 'erp_gl_store_takings') }}
