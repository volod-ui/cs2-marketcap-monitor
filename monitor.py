import json
import os
from pathlib import Path

import requests

API_URL = "https://api.pricempire.com/v4/trader/items/prices"
STATE_FILE = Path("state.json")
THRESHOLD = 10.0
SOURCE = "buff163"

api_key = os.environ["PRICEMPIRE_API_KEY"]
discord_webhook = os.environ["DISCORD_WEBHOOK"]

r = requests.get(
    API_URL,
    headers={"Authorization": f"Bearer {api_key}"},
    params={
        "app_id": 730,
        "currency": "USD",
        "sources": SOURCE,
    },
    timeout=90,
)

r.raise_for_status()
items = r.json()

previous = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
previous_prices = previous.get("prices", {})
current_prices = {}

for item in items:
    name = item.get("market_hash_name")

    if not name:
        continue

    for price_row in item.get("prices", []):
        if price_row.get("provider_key") != SOURCE:
            continue

        price = price_row.get("price")

        if price is None:
            continue

        try:
            current_prices[name] = float(price)
        except (TypeError, ValueError):
            pass

        break


movers = []

for name, price in current_prices.items():
    old = previous_prices.get(name)

    if old and old > 0:
        change = (price - old) / old * 100

        if abs(change) >= THRESHOLD:
            movers.append((change, name, price, old))


gainers = sorted(
    (x for x in movers if x[0] >= THRESHOLD),
    reverse=True
)[:10]

losers = sorted(
    (x for x in movers if x[0] <= -THRESHOLD)
)[:10]


def money_cents(value):
    return f"${value / 100:,.2f}"


lines = [
    "📊 **CS2 Price Monitor — 8h scan**",
    f"**Items scanned:** {len(current_prices):,}",
    f"**Source:** {SOURCE}",
]

lines.append("\n🚀 **Gainers ≥ +10%**")

if gainers:
    lines.extend(
        f"• `{name}` — **{change:+.2f}%** "
        f"({money_cents(old)} → {money_cents(price)})"
        for change, name, price, old in gainers
    )
else:
    lines.append("• None")


lines.append("\n🔻 **Losers ≤ -10%**")

if losers:
    lines.extend(
        f"• `{name}` — **{change:+.2f}%** "
        f"({money_cents(old)} → {money_cents(price)})"
        for change, name, price, old in losers
    )
else:
    lines.append("• None")


response = requests.post(
    discord_webhook,
    json={
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []},
    },
    timeout=30,
)

response.raise_for_status()


STATE_FILE.write_text(
    json.dumps(
        {"prices": current_prices},
        separators=(",", ":")
    )
)

print(
    f"Scanned {len(current_prices)} items; "
    f"movers: {len(movers)}"
)
