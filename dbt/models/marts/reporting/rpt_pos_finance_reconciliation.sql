-- Store takings per day: the tills (after cleaning) against the finance ledger.
-- Store-days with quarantined lines are expected to differ until the store corrects the line.
with pos as (
    select store_id, order_date as business_date, sum(revenue_nzd) as pos_revenue_nzd
    from {{ ref('fct_sales_lines') }}
    where sales_channel = 'store'
    group by 1, 2
),

ledger as (
    select store_id, posting_date as business_date, sum(amount_nzd) as ledger_amount_nzd
    from {{ ref('stg_erp__gl_store_takings') }}
    group by 1, 2
),

quarantined as (
    select store_id, txn_date as business_date, count(*) as quarantined_lines
    from {{ ref('int_dq__quarantined_pos_lines') }}
    group by 1, 2
)

select
    coalesce(pos.store_id, ledger.store_id)                                 as store_id,
    coalesce(pos.business_date, ledger.business_date)                       as business_date,
    round(coalesce(pos.pos_revenue_nzd, 0), 2)                              as pos_revenue_nzd,
    round(coalesce(ledger.ledger_amount_nzd, 0), 2)                         as ledger_amount_nzd,
    round(coalesce(pos.pos_revenue_nzd, 0) - coalesce(ledger.ledger_amount_nzd, 0), 2) as difference_nzd,
    coalesce(quarantined.quarantined_lines, 0)                              as quarantined_lines
from pos
full outer join ledger
    on pos.store_id = ledger.store_id
    and pos.business_date = ledger.business_date
left join quarantined
    on quarantined.store_id = coalesce(pos.store_id, ledger.store_id)
    and quarantined.business_date = coalesce(pos.business_date, ledger.business_date)
