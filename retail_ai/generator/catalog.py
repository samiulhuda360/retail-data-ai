"""Master data for Acme Kitchen Co., a fictional maker of kitchen and home products sold in New Zealand and Australia.

Everything here is invented: the company, its stores, its wholesale customers and its carriers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

START = date(2025, 4, 1)  # financial year FY2026: 1 April 2025 to 31 March 2026
END = date(2026, 3, 31)
AS_OF = "2026-04-01 06:00:00"  # the moment the landing zone is read (UTC)
SEED = 42


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    country: str


REGIONS = [
    Region("AKL", "Auckland", "NZ"),
    Region("WLG", "Wellington", "NZ"),
    Region("CHC", "Christchurch", "NZ"),
    Region("SYD", "Sydney", "AU"),
    Region("MEL", "Melbourne", "AU"),
]
REGION_BY_CODE = {r.code: r for r in REGIONS}


@dataclass(frozen=True)
class Store:
    store_id: str
    name: str
    region: str
    daily_txns: float  # average sale transactions on an ordinary weekday


STORES = [
    Store("S01", "Auckland Central", "AKL", 30),
    Store("S02", "Auckland North Shore", "AKL", 22),
    Store("S03", "Wellington Lambton", "WLG", 21),
    Store("S04", "Christchurch Riccarton", "CHC", 19),
    Store("S05", "Sydney CBD", "SYD", 28),
    Store("S06", "Sydney Parramatta", "SYD", 20),
    Store("S07", "Melbourne Southbank", "MEL", 24),
]


def currency_of(region_code: str) -> str:
    return "AUD" if REGION_BY_CODE[region_code].country == "AU" else "NZD"


# Material groups as the ERP codes them, and the category names the business uses.
CATEGORIES = {
    "CW": "Cookware",
    "BW": "Bakeware",
    "KT": "Kitchen Tools",
    "TW": "Tableware",
    "FS": "Food Storage",
}

# (description, list price NZD) per category; cost ratios differ by category so margins differ.
PRODUCTS: dict[str, list[tuple[str, float]]] = {
    "CW": [
        ("Cast Iron Skillet 26cm", 129.0),
        ("Stainless Saucepan 18cm", 89.0),
        ("Non-stick Frypan 28cm", 79.0),
        ("Enamel Dutch Oven 5L", 249.0),
        ("Stockpot 8L", 119.0),
        ("Carbon Steel Wok 32cm", 69.0),
        ("Ridged Grill Pan 26cm", 99.0),
        ("Saute Pan 24cm", 109.0),
        ("Milk Pan 14cm", 49.0),
        ("Oven Casserole 3L", 159.0),
        ("Bamboo Steamer Set", 39.0),
        ("Copper Saucepan 20cm", 219.0),
    ],
    "BW": [
        ("Loaf Tin 900g", 24.0),
        ("Springform Cake Tin 23cm", 32.0),
        ("Muffin Tray 12-cup", 29.0),
        ("Baking Sheet Large", 27.0),
        ("Pie Dish Ceramic 26cm", 39.0),
        ("Silicone Baking Mat", 19.0),
        ("Cooling Rack Tiered", 35.0),
        ("Bundt Tin 25cm", 45.0),
        ("Tart Tin Fluted 28cm", 26.0),
        ("Rolling Pin Beech", 22.0),
        ("Roasting Tray with Rack", 59.0),
        ("Pizza Stone 33cm", 49.0),
    ],
    "KT": [
        ("Chef's Knife 20cm", 89.0),
        ("Silicone Spatula Set", 19.0),
        ("Digital Kitchen Scale", 39.0),
        ("Balloon Whisk 30cm", 15.0),
        ("Microplane Grater", 29.0),
        ("Measuring Cup Set", 18.0),
        ("Tongs Locking 30cm", 14.0),
        ("Garlic Press", 22.0),
        ("Bamboo Chopping Board", 45.0),
        ("Instant-read Thermometer", 34.0),
        ("Pepper Mill Oak", 49.0),
        ("Mandoline Slicer", 59.0),
    ],
    "TW": [
        ("Stoneware Dinner Plate", 22.0),
        ("Stoneware Side Plate", 16.0),
        ("Pasta Bowl Set of 4", 69.0),
        ("Tumbler Set of 6", 39.0),
        ("Wine Glass Pair", 35.0),
        ("Serving Platter Oval", 55.0),
        ("Linen Napkins Set of 4", 29.0),
        ("Cutlery Set 24-piece", 119.0),
        ("Espresso Cup Pair", 25.0),
        ("Salad Bowl Acacia", 65.0),
        ("Table Runner Linen", 39.0),
        ("Cheese Board Slate", 45.0),
    ],
    "FS": [
        ("Glass Container 1L", 14.0),
        ("Glass Container Set of 5", 49.0),
        ("Beeswax Wraps 3-pack", 24.0),
        ("Pantry Jar 2L", 19.0),
        ("Lunch Box Bento", 29.0),
        ("Spice Jar Set of 12", 39.0),
        ("Bread Bin Enamel", 69.0),
        ("Vacuum Canister 1.5L", 34.0),
        ("Silicone Food Bags 4-pack", 27.0),
        ("Flour Canister 3L", 32.0),
        ("Fridge Organiser Set", 45.0),
        ("Insulated Food Flask", 39.0),
    ],
}
COST_RATIO = {"CW": 0.44, "BW": 0.38, "KT": 0.36, "TW": 0.41, "FS": 0.33}
AUD_PRICE_FACTOR = 0.93  # Australian list prices are set in AUD at about 93% of the NZD price

# A product launched in March 2026 that the ERP master-data export does not include yet.
LATE_MATERIAL = ("MAT-1061", "AK-CW-13", "Enamel Roasting Dish 35cm", "CW", 139.0, date(2026, 3, 9))

# Wholesale customers: independent homeware retailers (invented).
CUSTOMERS = [
    ("CUST-001", "Tui Lane Homewares", "AKL"),
    ("CUST-002", "Brightwater Kitchens", "AKL"),
    ("CUST-003", "Copperleaf Home", "AKL"),
    ("CUST-004", "Fernhill Cookshop", "WLG"),
    ("CUST-005", "Harbour and Hearth", "WLG"),
    ("CUST-006", "Kowhai Kitchen Supply", "CHC"),
    ("CUST-007", "Plainsview Living", "CHC"),
    ("CUST-008", "Totara Table", "AKL"),
    ("CUST-009", "Riverstone Homeware", "CHC"),
    ("CUST-010", "Seaview Pantry", "WLG"),
    ("CUST-011", "Bluegum Homeware", "SYD"),
    ("CUST-012", "Wattle Street Kitchens", "SYD"),
    ("CUST-013", "Saltbush Living", "MEL"),
    ("CUST-014", "Laneway Cook Co.", "MEL"),
    ("CUST-015", "Ironbark Home", "SYD"),
    ("CUST-016", "Banksia Table", "MEL"),
]

SALES_CHANNELS = ["store", "online", "wholesale"]
MARKETING_CHANNELS = ["paid_search", "paid_social", "display", "email", "affiliate"]
UNPAID_CHANNEL = "organic"
# Return on ad spend each paid channel delivers on average (attributed revenue / spend).
TARGET_ROAS = {"paid_search": 4.2, "paid_social": 2.6, "display": 1.4, "email": 9.0, "affiliate": 5.5}
ATTRIBUTION_SHARE = {
    "paid_search": 0.28,
    "paid_social": 0.22,
    "display": 0.05,
    "email": 0.12,
    "affiliate": 0.08,
    "organic": 0.25,
}

# Carriers by country, with the share of deliveries each makes on time in a normal week.
CARRIERS = {
    "NZ": [("Kiwi Express", 0.95), ("Harbour Freight", 0.90)],
    "AU": [("Coastal Couriers", 0.88), ("Outback Parcel", 0.93)],
}

MONTH_FACTOR = {
    4: 0.90,
    5: 0.95,
    6: 1.00,
    7: 1.05,
    8: 0.95,
    9: 0.95,
    10: 1.00,
    11: 1.25,
    12: 1.50,
    1: 0.85,
    2: 0.85,
    3: 0.90,
}
STORE_DOW = [0.80, 0.85, 0.90, 1.00, 1.10, 1.35, 1.15]  # Monday first
ONLINE_DOW = [1.10, 1.05, 1.00, 0.95, 0.90, 0.95, 1.10]
CATEGORY_MONTH_BOOST = {
    "CW": {6: 1.25, 7: 1.3, 8: 1.15},  # winter cooking
    "BW": {12: 1.4, 6: 1.1},
    "TW": {12: 1.5, 11: 1.2, 1: 1.1},
    "FS": {1: 1.3, 2: 1.4},  # back to school lunch boxes
    "KT": {11: 1.15, 12: 1.3},
}

BLACK_FRIDAY = (date(2025, 11, 28), date(2025, 12, 1))
BOXING_DAY_SALE = (date(2025, 12, 26), date(2026, 1, 4))

CAMPAIGNS = [
    # (start, end, name)
    (date(2025, 4, 1), date(2025, 5, 31), "Autumn Kitchen Refresh"),
    (date(2025, 6, 1), date(2025, 8, 31), "Winter Warmers"),
    (date(2025, 9, 1), date(2025, 11, 20), "Spring Entertaining"),
    (date(2025, 11, 21), date(2025, 12, 1), "Black Friday"),
    (date(2025, 12, 2), date(2025, 12, 25), "Christmas Gifting"),
    (date(2025, 12, 26), date(2026, 1, 31), "Summer Sale"),
    (date(2026, 2, 1), date(2026, 3, 31), "Back to School Lunches"),
]


def campaign_for(day: date) -> str:
    for start, end, name in CAMPAIGNS:
        if start <= day <= end:
            return name
    return "Always On"
