-- The till feed delivered one store-day twice. Number the copies of each transaction line with ROW_NUMBER,
-- keep copy 1, and show where the extra copies were (the staging model stg_pos__transaction_lines does the same).
with ranked as (
    select
        *,
        row_number() over (
            partition by transaction_id, line_no
            order by _source_file, cast(_extracted_at as timestamp)
        ) as copy_number
    from raw.pos_transactions
)

select
    store_id,
    cast(cast(txn_ts as timestamp) as date)          as business_date,
    count(*)                                         as lines_delivered,
    count(*) filter (where copy_number = 1)          as lines_kept,
    count(*) filter (where copy_number > 1)          as duplicate_lines_removed,
    round(sum(cast(line_total as decimal(12, 2))) filter (where copy_number > 1), 2)
                                                     as duplicated_takings
from ranked
group by 1, 2
having count(*) filter (where copy_number > 1) > 0
order by duplicate_lines_removed desc;
