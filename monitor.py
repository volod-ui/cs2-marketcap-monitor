import json
import os
from pathlib import Path
import requests

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://api.pricempire.com/v4/paid/items/prices"
STATE_FILE = Path("state.json")

# Alert thresholds
THRESHOLD = 7.5
STRONG_THRESHOLD = 15.0

# Liquidity filters
MIN_LIQUIDITY = 85.0
MIN_TRADES_7D = 50          # ← aangepast naar jouw eis
MIN_LISTINGS = 5

# Minimum price (EUR)
MIN_PRICE_EUR = 3.0         # ← aangepast naar jouw eis

# Steam + csfloat
SOURCES = "steam,csfloat"    # ← aangepast

APP_ID = 730
CURRENCY = "EUR"             # ← aangepast

API_KEY = os.environ["PRICEMPIRE_API_KEY"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]


# ============================================================
# LOAD PREVIOUS STATE
# ============================================================

if STATE_FILE.exists():
    try:
        previous = json.loads(STATE_FILE.read_text(encoding="utf-8"))
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
        "sources": SOURCES,
        "metas": "liquidity,trades_7d,count",
    },
    timeout=90,
)

response.raise_for_status()
items = response.json()

if not isinstance(items, list):
    raise RuntimeError(f"Unexpected API response type: {type(items).__name__}")


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
    liquidity = float(item.get("liquidity", 0))
    if liquidity < MIN_LIQUIDITY:
        filtered_liquidity += 1
        continue

    # --------------------------------------------------------
    # Trades 7d
    # --------------------------------------------------------
    trades_7d = int(float(item.get("trades_7d", 0)))
    if trades_7d < MIN_TRADES_7D:
        filtered_volume += 1
        continue

    # --------------------------------------------------------
    # Listings
    # --------------------------------------------------------
    listing_count = int(float(item.get("count", 0)))
    if listing_count < MIN_LISTINGS:
        filtered_listings += 1
        continue

    # --------------------------------------------------------
    # Steam price (EUR cents)
    # --------------------------------------------------------
    steam_price = None

    for price_row in item.get("prices", []):
        if price_row.get("provider_key") != "steam":
            continue

        price = price_row.get("price")
        if price is None:
            continue

        try:
            price = float(price)
        except:
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
    # Minimum price (EUR)
    # Pricempire returns cents → divide by 100
    # --------------------------------------------------------
    price_eur = steam_price / 100
    if price_eur < MIN_PRICE_EUR:
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

    old_price = old["price"] if isinstance(old, dict) else old
    if old_price is None:
        continue

    try:
        old_price = float(old_price)
    except:
        continue

    if old_price <= 0:
        continue

    current_price = current["price"]
    change = ((current_price - old_price) / old_price) * 100

    if abs(change) < THRESHOLD:
        continue

    movers.append({
        "name": name,
        "old_price": old_price,
        "new_price": current_price,
        "change": change,
        "liquidity": current["liquidity"],
        "trades_7d": current["trades_7d"],
        "count": current["count"],
    })


# ============================================================
# SORT MOVERS
# ============================================================

gainers = sorted(
    [m for m in movers if m["change"] >= THRESHOLD],
    key=lambda m: m["change"],
    reverse=True
)[:10]

losers = sorted(
    [m for m in movers if m["change"] <= -THRESHOLD],
    key=lambda m: m["change"]
)[:10]


# ============================================================
# DISCORD HELPERS
# ============================================================

def eur(value):
    return f"€{value / 100:,.2f}"


def movement_icon(change):
    if change >= STRONG_THRESHOLD:
        return "🔥"
    if change >= THRESHOLD:
        return "🟢"
    if change <= -STRONG_THRESHOLD:
        return "🚨"
    return "🔴"


def movement_label(change):
    return "STRONG" if abs(change) >= STRONG_THRESHOLD else "INTERESTING"


# ============================================================
# BUILD DISCORD MESSAGE
# ============================================================

msg = []
msg.append("📊 **CS2 STEAM MARKET — SCAN**")
msg.append("")
msg.append(f"**Items monitored:** {qualified_items:,}")
msg.append(f"**Filter:** Liquidity ≥ {MIN_LIQUIDITY:.0f} | Trades 7d ≥ {MIN_TRADES_7D} | Listings ≥ {MIN_LISTINGS}")
msg.append(f"**Minimum price:** €{MIN_PRICE_EUR:.2f}")
msg.append(f"**Alert:** ±{THRESHOLD:.1f}%")
msg.append(f"**Strong movement:** ±{STRONG_THRESHOLD:.0f}%")
msg.append("**Sources:** Steam + CSFloat")

# Gainers
if gainers:
    msg.append("")
    msg.append(f"🚀 **GAINERS ≥ +{THRESHOLD:.1f}%**")
    for item in gainers:
        icon = movement_icon(item["change"])
        label = movement_label(item["change"])
        msg.append(
            f"{icon} **{item['name']}** `+{item['change']:.2f}%` "
            f"({eur(item['old_price'])} → {eur(item['new_price'])}) • {label}"
        )
        msg.append(
            f"   Liquidity: {item['liquidity']:.0f} | 7d trades: {item['trades_7d']} | listings: {item['count']}"
        )

# Losers
if losers:
    msg.append("")
    msg.append(f"🔻 **LOSERS ≤ -{THRESHOLD:.1f}%**")
    for item in losers:
        icon = movement_icon(item["change"])
        label = movement_label(item["change"])
        msg.append(
            f"{icon} **{item['name']}** `{item['change']:.2f}%` "
            f"({eur(item['old_price'])} → {eur(item['new_price'])}) • {label}"
        )
        msg.append(
            f"   Liquidity: {item['liquidity']:.0f} | 7d trades: {item['trades_7d']} | listings: {item['count']}"
        )

if not gainers and not losers:
    msg.append("")
    msg.append("ℹ️ **Geen significante prijsbewegingen gevonden.**")

message = "\n".join(msg)


# ============================================================
# SEND TO DISCORD
# ============================================================

discord_response = requests.post(
    DISCORD_WEBHOOK,
    json={"content": message, "allowed_mentions": {"parse": []}},
    timeout=30,
)
discord_response.raise_for_status()


# ============================================================
# SAVE STATE
# ============================================================

STATE_FILE.write_text(
    json.dumps({"prices": current_prices}, separators=(",", ":")),
    encoding="utf-8",
)

print("Scan completed successfully.")
