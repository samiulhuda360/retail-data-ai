-- Till lines, one row per transaction line.
--   * Duplicate deliveries are removed: the first copy of each (transaction_id, line_no) is kept.
--   * The currency comes from the store master; the label in the file is kept as reported_currency.
--   * A SALE line must have a positive quantity; other lines are flagged here and quarantined downstream.
with source as (
    select * from {{ source('raw', 'pos_transactions') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by transaction_id, line_no
            order by _source_file, cast(_extracted_at as timestamp)
        ) as copy_number
    from source
),

stores as (
    select * from {{ ref('stg_erp__stores') }}
)

select
    ranked.transaction_id || '-' || ranked.line_no      as pos_line_id,
    ranked.store_id,
    ranked.transaction_id,
    cast(ranked.line_no as integer)                     as line_no,
    cast(ranked.txn_ts as timestamp)                    as txn_ts,
    cast(cast(ranked.txn_ts as timestamp) as date)      as txn_date,
    ranked.txn_type,
    ranked.sku,
    cast(ranked.quantity as integer)                    as quantity,
    cast(ranked.unit_price as decimal(12, 2))           as unit_price,
    cast(ranked.discount_amount as decimal(12, 2))      as discount_amount,
    cast(ranked.line_total as decimal(12, 2))           as line_total,
    stores.currency                                     as currency,
    ranked.currency                                     as reported_currency,
    ranked.payment_method,
    not (ranked.txn_type = 'SALE' and cast(ranked.quantity as integer) <= 0) as is_valid,
    ranked._source_file
from ranked
left join stores on ranked.store_id = stores.store_id
where ranked.copy_number = 1
