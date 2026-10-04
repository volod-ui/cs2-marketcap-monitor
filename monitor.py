import json
import os
from pathlib import Path
import requests

# ============================================================
# CONFIG
# ============================================================

API_URL = "https://api.pricempire.com/v4/free/items/prices"
STATE_FILE = Path("state.json")

MIN_CHANGE = 7.5      # minimum percentage
MAX_CHANGE = 50.0     # maximum percentage
STRONG_CHANGE = 15.0  # strong movement threshold

APP_ID = 730
CURRENCY = "USD"      # free tier only supports USD
SOURCE = "steam"      # free tier only supports steam

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
# FETCH DATA
# ============================================================

response = requests.get(
    API_URL,
    headers={"Authorization": f"Bearer {API_KEY}"},
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
    raise RuntimeError("Unexpected API response format")


# ============================================================
# PROCESS ITEMS
# ============================================================

current_prices = {}

for item in items:
    name = item.get("market_hash_name")
    if not name:
        continue

    steam_price = None

    for row in item.get("prices", []):
        if row.get("provider_key") != SOURCE:
            continue

        price = row.get("price")
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
# DETECT MOVERS
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

    # Only include movements between MIN and MAX
    if MIN_CHANGE <= abs(change) <= MAX_CHANGE:
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
    [m for m in movers if m["change"] >= MIN_CHANGE],
    key=lambda m: m["change"],
    reverse=True
)[:10]

losers = sorted(
    [m for m in movers if m["change"] <= -MIN_CHANGE],
    key=lambda m: m["change"]
)[:10]


# ============================================================
# DISCORD HELPERS
# ============================================================

def usd(value):
    return f"${value / 100:,.2f}"

def icon(change):
    if change >= STRONG_CHANGE:
        return "🔥"
    if change >= MIN_CHANGE:
        return "🟢"
    if change <= -STRONG_CHANGE:
        return "🚨"
    return "🔴"


# ============================================================
# BUILD MESSAGE
# ============================================================

msg = []
msg.append("📊 **CS2 STEAM MARKET — FREE TIER SCAN**")
msg.append("")
msg.append(f"**Items scanned:** {len(current_prices):,}")
msg.append(f"**Alert range:** {MIN_CHANGE}% → {MAX_CHANGE}%")
msg.append(f"**Strong movement:** ±{STRONG_CHANGE}%")
msg.append("**Source:** Steam (FREE tier)")

if gainers:
    msg.append("")
    msg.append(f"🚀 **GAINERS ≥ +{MIN_CHANGE}%**")
    for m in gainers:
        msg.append(
            f"{icon(m['change'])} **{m['name']}** "
            f"`+{m['change']:.2f}%` "
            f"({usd(m['old'])} → {usd(m['new'])})"
        )

if losers:
    msg.append("")
    msg.append(f"🔻 **LOSERS ≤ -{MIN_CHANGE}%**")
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
