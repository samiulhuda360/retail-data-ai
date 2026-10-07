-- Where a sale happened: store, online or wholesale.
select sales_channel, channel_name, description
from {{ ref('sales_channels') }}
