-- The channel an online order is attributed to, and whether it is paid media.
select marketing_channel, channel_name, cast(is_paid as boolean) as is_paid, platform
from {{ ref('marketing_channels') }}
