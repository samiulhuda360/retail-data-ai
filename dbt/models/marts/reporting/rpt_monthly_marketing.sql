-- Monthly spend, attributed online revenue and return on ad spend for each paid channel.
with spend as (
    select
        cast({{ dbt.date_trunc('month', 'spend_date') }} as date)  as month,
        marketing_channel,
        sum(spend_nzd)                                              as ad_spend_nzd
    from {{ ref('fct_ad_spend') }}
    group by 1, 2
),

attributed as (
    select
        cast({{ dbt.date_trunc('month', 'order_date') }} as date)  as month,
        marketing_channel,
        sum(revenue_nzd)                                            as attributed_revenue_nzd
    from {{ ref('fct_orders') }}
    where is_paid_attribution and order_type = 'sale'
    group by 1, 2
)

select
    coalesce(spend.month, attributed.month)                                         as month,
    coalesce(spend.marketing_channel, attributed.marketing_channel)                 as marketing_channel,
    round(coalesce(spend.ad_spend_nzd, 0), 2)                                       as ad_spend_nzd,
    round(coalesce(attributed.attributed_revenue_nzd, 0), 2)                        as attributed_revenue_nzd,
    round(attributed.attributed_revenue_nzd / nullif(spend.ad_spend_nzd, 0), 4)     as roas
from spend
full outer join attributed
    on spend.month = attributed.month
    and spend.marketing_channel = attributed.marketing_channel
