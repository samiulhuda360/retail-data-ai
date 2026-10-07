-- Till lines held back from the marts because they break a business rule, with the reason.
-- They stay visible here (and in the data-quality report) until the store corrects them.
select
    pos_line_id,
    store_id,
    transaction_id,
    line_no,
    txn_date,
    txn_type,
    sku,
    quantity,
    line_total,
    currency,
    'SALE line with a non-positive quantity' as reason,
    _source_file
from {{ ref('stg_pos__transaction_lines') }}
where not is_valid
