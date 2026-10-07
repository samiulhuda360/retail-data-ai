-- Paid media cost from three platforms with three export formats, unioned into one shape:
-- one row per day, channel, region and campaign, in the billing currency.
with search as (
    select
        {{ parse_date('date', 'yyyy-mm-dd') }}          as spend_date,
        'paid_search'                                   as marketing_channel,
        split_part(geo_target, '-', 2)                  as region_code,
        campaign_name,
        currency,
        cast(cost_micros as bigint) / 1000000.0         as spend_local,
        cast(impressions as bigint)                     as impressions,
        cast(clicks as bigint)                          as clicks,
        'search_ads'                                    as source_platform
    from {{ source('raw', 'mkt_search_ads') }}
),

social as (
    select
        {{ parse_date('social.day', 'dd/mm/yyyy') }}    as spend_date,
        'paid_social'                                   as marketing_channel,
        regions.region_code,
        social.campaign_name,
        social.currency,
        cast(social.amount_spent as double)             as spend_local,
        cast(social.reach as bigint)                    as impressions,
        cast(social.link_clicks as bigint)              as clicks,
        'social_ads'                                    as source_platform
    from {{ source('raw', 'mkt_social_ads') }} as social
    left join {{ ref('regions') }} as regions on social.region = regions.region_name
),

other as (
    select
        {{ parse_date('date', 'yyyy-mm-dd') }}          as spend_date,
        channel                                         as marketing_channel,
        region_code,
        cast(null as varchar)                           as campaign_name,
        currency,
        cast(spend as double)                           as spend_local,
        cast(null as bigint)                            as impressions,
        cast(null as bigint)                            as clicks,
        'other_channels'                                as source_platform
    from {{ source('raw', 'mkt_other_channels') }}
)

select * from search
union all
select * from social
union all
select * from other
