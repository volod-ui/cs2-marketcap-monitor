```python
import json
import os
from pathlib import Path

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://api.pricempire.com/v4/trader/items/prices"

STATE_FILE = Path("state.json")

# Alert thresholds
THRESHOLD = 7.5
STRONG_THRESHOLD = 15.0

# Liquidity filters
MIN_LIQUIDITY = 85.0
MIN_TRADES_7D = 25
MIN_LISTINGS = 5

# Ignore very cheap items
MIN_PRICE_USD = 5.0

# Steam market
SOURCE = "steam"

# CS2
APP_ID = 730
CURRENCY = "USD"

# Secrets
API_KEY = os.environ["PRICEMPIRE_API_KEY"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]


# ============================================================
# LOAD PREVIOUS STATE
# ============================================================

if STATE_FILE.exists():
    try:
        previous = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        previous = {}
else:
    previous = {}

previous_prices = previous.get("prices", {})


# ============================================================
# FETCH DATA FROM PRICEMPIRE
# ============================================================

response = requests.get(
    API_URL,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
    },
    params={
        "app_id": APP_ID,
        "currency": CURRENCY,
        "sources": SOURCE,
        "metas": "liquidity,trades_7d,count",
    },
    timeout=90,
)

response.raise_for_status()

items = response.json()

if not isinstance(items, list):
    raise RuntimeError(
        f"Unexpected API response type: {type(items).__name__}"
    )


# ============================================================
# PROCESS ITEMS
# ============================================================

current_prices = {}

qualified_items = 0

filtered_liquidity = 0
filtered_volume = 0
filtered_listings = 0
filtered_price = 0
filtered_zero_price = 0


for item in items:

    name = item.get("market_hash_name")

    if not name:
        continue

    # --------------------------------------------------------
    # Liquidity
    # --------------------------------------------------------

    try:
        liquidity = float(item.get("liquidity", 0))
    except (TypeError, ValueError):
        liquidity = 0.0

    if liquidity < MIN_LIQUIDITY:
        filtered_liquidity += 1
        continue

    # --------------------------------------------------------
    # 7-day trades
    # --------------------------------------------------------

    try:
        trades_7d = int(float(item.get("trades_7d", 0)))
    except (TypeError, ValueError):
        trades_7d = 0

    if trades_7d < MIN_TRADES_7D:
        filtered_volume += 1
        continue

    # --------------------------------------------------------
    # Listings
    # --------------------------------------------------------

    try:
        listing_count = int(float(item.get("count", 0)))
    except (TypeError, ValueError):
        listing_count = 0

    if listing_count < MIN_LISTINGS:
        filtered_listings += 1
        continue

    # --------------------------------------------------------
    # Find Steam price
    # --------------------------------------------------------

    steam_price = None

    for price_row in item.get("prices", []):

        if price_row.get("provider_key") != SOURCE:
            continue

        price = price_row.get("price")

        if price is None:
            continue

        try:
            price = float(price)
        except (TypeError, ValueError):
            continue

        if price <= 0:
            steam_price = None
            break

        steam_price = price
        break

    if steam_price is None:
        filtered_zero_price += 1
        continue

    # --------------------------------------------------------
    # Minimum price
    #
    # Pricempire is expected to return the price in cents
    # for this endpoint, therefore divide by 100 here.
    # --------------------------------------------------------

    price_usd = steam_price / 100

    if price_usd < MIN_PRICE_USD:
        filtered_price += 1
        continue

    # --------------------------------------------------------
    # Save qualified item
    # --------------------------------------------------------

    current_prices[name] = {
        "price": steam_price,
        "liquidity": liquidity,
        "trades_7d": trades_7d,
        "count": listing_count,
    }

    qualified_items += 1


# ============================================================
# CALCULATE PRICE MOVEMENTS
# ============================================================

movers = []

for name, current in current_prices.items():

    old = previous_prices.get(name)

    if old is None:
        continue

    # Support both old format and dictionary format
    if isinstance(old, dict):
        old_price = old.get("price")
    else:
        old_price = old

    if old_price is None:
        continue

    try:
        old_price = float(old_price)
    except (TypeError, ValueError):
        continue

    if old_price <= 0:
        continue

    current_price = current["price"]

    change = (
        (current_price - old_price)
        / old_price
    ) * 100

    if abs(change) < THRESHOLD:
        continue

    movers.append(
        {
            "name": name,
            "old_price": old_price,
            "new_price": current_price,
            "change": change,
            "liquidity
```
