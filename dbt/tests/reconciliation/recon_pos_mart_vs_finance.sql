-- After cleaning, store revenue in the marts must agree with the finance ledger for every store-day,
-- except store-days that have a quarantined line (those are listed by int_dq__quarantined_pos_lines).
{{ config(severity='error', tags=['reconciliation']) }}

select *
from {{ ref('rpt_pos_finance_reconciliation') }}
where abs(difference_nzd) > {{ var('recon_tolerance_nzd') }}
  and quarantined_lines = 0
