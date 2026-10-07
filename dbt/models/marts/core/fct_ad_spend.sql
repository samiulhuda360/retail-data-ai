-- Grain: one day x marketing channel x region x campaign. Spend in NZD.
select
    spend_date || '|' || marketing_channel || '|' || region_code || '|' || coalesce(campaign_name, '-') as spend_id,
    spend_date,
    marketing_channel,
    region_code,
    campaign_name,
    source_platform,
    currency                as billing_currency,
    spend_local,
    spend_nzd,
    impressions,
    clicks
from {{ ref('int_marketing__spend_nzd') }}
