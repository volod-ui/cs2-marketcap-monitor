import json
import os
from pathlib import Path

import requests

API_URL = "https://api.pricempire.com/v4/trader/items/prices"
STATE_FILE = Path("state.json")
THRESHOLD = 10.0

api_key = os.environ["PRICEMPIRE_API_KEY"]
discord_webhook = os.environ["DISCORD_WEBHOOK"]

response = requests.get(
    API_URL,
    headers={"Authorization": f"Bearer {api_key}"},
    params={
        "app_id": 730,
        "currency": "USD",
        "metas": "marketcap",
    },
    timeout=90,
)

response.raise_for_status()
items = response.json()

if STATE_FILE.exists():
    previous = json.loads(STATE_FILE.read_text())
else:
    previous = {}

current = {}
total_marketcap = 0.0

for item in items:
    name = item.get("market_hash_name")
    marketcap = item.get("marketcap")

    if not name or marketcap is None:
        continue

    try:
        marketcap = float(marketcap)
    except (TypeError, ValueError):
        continue

    current[name] = marketcap
    total_marketcap += marketcap


previous_items = previous.get("items", {})
movers = []

for name, value in current.items():
    old_value = previous_items.get(name)

    if old_value and old_value > 0:
        change = ((value - old_value) / old_value) * 100

        if abs(change) >= THRESHOLD:
            movers.append((change, name))


gainers = sorted(
    [x for x in movers if x[0] >= THRESHOLD],
    reverse=True
)[:10]

losers = sorted(
    [x for x in movers if x[0] <= -THRESHOLD]
)[:10]


old_total = previous.get("total_marketcap")

if old_total and old_total > 0:
    total_change = ((total_marketcap - old_total) / old_total) * 100
else:
    total_change = None


def money(value):
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    elif value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value / 1_000:.1f}K"
    else:
        return f"${value:.0f}"


def percentage(value):
    return f"{value:+.2f}%"


message = [
    "📊 **CS2 Market Cap — 8h scan**",
    f"**Total market cap:** {money(total_marketcap)}",
]

if total_change is not None:
    message.append(
        f"**Since previous scan:** {percentage(total_change)}"
    )
else:
    message.append(
        "**Since previous scan:** first scan — baseline created"
    )


message.append("")
message.append("🚀 **Gainers ≥ +10%**")

if gainers:
    for change, name in gainers:
        message.append(
            f"• `{name}` — {percentage(change)}"
        )
else:
    message.append("• None")


message.append("")
message.append("🔻 **Losers ≤ -10%**")

if losers:
    for change, name in losers:
        message.append(
            f"• `{name}` — {percentage(change)}"
        )
else:
    message.append("• None")


payload = {
    "content": "\n".join(message),
    "allowed_mentions": {
        "parse": []
    },
}

discord_response = requests.post(
    discord_webhook,
    json=payload,
    timeout=30,
)

discord_response.raise_for_status()


new_state = {
    "total_marketcap": total_marketcap,
    "items": current,
}

STATE_FILE.write_text(
    json.dumps(new_state, separators=(",", ":"))
)

print(
    f"Scanned {len(current)} items. "
    f"Total market cap: {total_marketcap:.2f}"
)
