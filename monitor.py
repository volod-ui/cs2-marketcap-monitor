import json
import os
from pathlib import Path
import requests

# ============================================================
# CONFIGURATION
# ============================================================

API_URL = "https://api.pricempire.com/v4/free/items/prices"
STATE_FILE = Path("state.json")

THRESHOLD_MIN = 7.5
THRESHOLD_MAX = 50.0
STRONG_THRESHOLD = 15.0

APP_ID = 730
CURRENCY = "USD"   # Free tier ondersteunt enkel USD
SOURCE = "steam"   # Free tier ondersteunt enkel Steam

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
# FETCH DATA FROM PRICEMPIRE (FREE TIER)
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
    },
    timeout=60,
)

response.raise_for_status()
items = response.json()

if not isinstance(items, list):
    raise RuntimeError(f"Unexpected API response type: {type(items).__name__}")


# ============================================================
# PROCESS ITEMS
# ============================================================

current_prices = {}

for item in items:
    name = item.get("market_hash_name")
    if not name:
        continue

    steam_price = None

    for price_row in item.get("prices", []):
        if price_row.get("provider_key") != SOURCE:
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
        continue

    current_prices[name] = steam_price


# ============================================================
# CALCULATE MOVEMENTS
# ============================================================

movers = []

for name, new_price in current_prices.items():
    old_price = previous_prices.get(name)

    if old_price is None:
        continue

    try:
        old_price = float(old_price)
    except:
        continue

    if old_price <= 0:
        continue

    change = ((new_price - old_price) / old_price) * 100

    # Alleen alerts tussen 7.5% en 50%
    if THRESHOLD_MIN <= abs(change) <= THRESHOLD_MAX:
        movers.append({
            "name": name,
            "old": old_price,
            "new": new_price,
            "change": change,
        })


# ============================================================
# SORT MOVERS
# ============================================================

gainers = sorted(
    [m for m in movers if m["change"] >= THRESHOLD_MIN],
    key=lambda m: m["change"],
    reverse=True
)[:10]

losers = sorted(
    [m for m in movers if m["change"] <= -THRESHOLD_MIN],
    key=lambda m: m["change"]
)[:10]


# ============================================================
# DISCORD HELPERS
# ============================================================

def usd(value):
    return f"${value / 100:,.2f}"


def icon(change):
    if change >= STRONG_THRESHOLD:
        return "🔥"
    if change >= THRESHOLD_MIN:
        return "🟢"
    if change <= -STRONG_THRESHOLD:
        return "🚨"
    return "🔴"


# ============================================================
# BUILD DISCORD MESSAGE
# ============================================================

msg = []
msg.append("📊 **CS2 STEAM MARKET — FREE TIER SCAN**")
msg.append("")
msg.append(f"**Items scanned:** {len(current_prices):,}")
msg.append(f"**Alert range:** ±{THRESHOLD_MIN:.1f}% → ±{THRESHOLD_MAX:.1f}%")
msg.append(f"**Strong:** ±{STRONG_THRESHOLD:.0f}%")
msg.append("**Source:** Steam (FREE tier)")

if gainers:
    msg.append("")
    msg.append(f"🚀 **GAINERS ≥ +{THRESHOLD_MIN:.1f}%**")
    for m in gainers:
        msg.append(
            f"{icon(m['change'])} **{m['name']}** "
            f"`+{m['change']:.2f}%` "
            f"({usd(m['old'])} → {usd(m['new'])})"
        )

if losers:
    msg.append("")
    msg.append(f"🔻 **LOSERS ≤ -{THRESHOLD_MIN:.1f}%**")
    for m in losers:
        msg.append(
            f"{icon(m['change'])} **{m['name']}** "
            f"`{m['change']:.2f}%` "
            f"({usd(m['old'])} → {usd(m['new'])})"
        )

if not gainers and not losers:
    msg.append("")
    msg.append("ℹ️ **Geen significante prijsbewegingen gevonden.**")

message = "\n".join(msg)


# ============================================================
# SEND TO DISCORD
# ============================================================

requests.post(
    DISCORD_WEBHOOK,
    json={"content": message, "allowed_mentions": {"parse": []}},
    timeout=30,
).raise_for_status()


# ============================================================
# SAVE STATE
# ============================================================

STATE_FILE.write_text(
    json.dumps({"prices": current_prices}, separators=(",", ":")),
    encoding="utf-8",
)

print("Scan completed successfully.")
