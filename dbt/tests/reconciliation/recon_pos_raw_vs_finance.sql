-- Reconciles the till files exactly as delivered against the finance ledger, store by store and day by day.
-- Duplicated lines, mislabelled currency and keying errors all show up as store-days that do not agree.
{{ config(severity='warn', tags=['dq_detect', 'reconciliation']) }}

with fx as (
    select {{ parse_date('RATE_DATE', 'yyyymmdd') }} as rate_date, cast(RATE as decimal(10, 4)) as rate
    from {{ source('raw', 'erp_fx_rates') }}
),

pos as (
    select
        store_id,
        cast(cast(txn_ts as timestamp) as date)                 as business_date,
        sum({{ to_nzd('cast(line_total as decimal(12, 2))', 'currency', 'fx.rate') }}) as pos_nzd
    from {{ source('raw', 'pos_transactions') }}
    left join fx on cast(cast(txn_ts as timestamp) as date) = fx.rate_date
    group by 1, 2
),

ledger as (
    select STORE_ID as store_id, {{ parse_date('POSTING_DATE', 'yyyymmdd') }} as business_date,
           sum(cast(AMOUNT_NZD as decimal(14, 2))) as ledger_nzd
    from {{ source('raw', 'erp_gl_store_takings') }}
    group by 1, 2
)

select
    coalesce(pos.store_id, ledger.store_id)             as store_id,
    coalesce(pos.business_date, ledger.business_date)   as business_date,
    round(pos.pos_nzd, 2)                               as pos_nzd,
    ledger.ledger_nzd,
    round(coalesce(pos.pos_nzd, 0) - coalesce(ledger.ledger_nzd, 0), 2) as difference_nzd
from pos
full outer join ledger on pos.store_id = ledger.store_id and pos.business_date = ledger.business_date
where abs(coalesce(pos.pos_nzd, 0) - coalesce(ledger.ledger_nzd, 0)) > {{ var('recon_tolerance_nzd') }}
