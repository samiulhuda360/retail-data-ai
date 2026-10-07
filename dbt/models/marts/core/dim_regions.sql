-- Sales regions: the five metro areas the business reports on.
select region_code, region_name, country
from {{ ref('regions') }}
