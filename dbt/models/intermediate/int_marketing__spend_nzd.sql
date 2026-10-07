-- Ad spend converted to NZD at the day's rate.
with spend as (
    select * from {{ ref('stg_marketing__ad_spend') }}
),

fx as (
    select * from {{ ref('stg_erp__fx_rates') }}
)

select
    spend.*,
    {{ to_nzd('spend.spend_local', 'spend.currency', 'fx.aud_nzd_rate') }} as spend_nzd
from spend
left join fx on spend.spend_date = fx.rate_date
