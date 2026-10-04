import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URL = "https://www.brickeconomy.com/minifigs/retiring-soon"
STATE_FILE = Path("brickeconomy_state.json")
THRESHOLD = 5.0

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_BRICKECONOMY"]


headers = {
    "User-Agent": "Mozilla/5.0 (compatible; BrickEconomyMonitor/1.0)"
}


response = requests.get(
    URL,
    headers=headers,
    timeout=60,
)

response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

current = {}


# Read minifigures from the Retiring Soon page.
for link in soup.find_all("a", href=True):

    href = link.get("href", "")
    text = " ".join(link.stripped_strings)

    if not href.startswith("/minifig/"):
        continue

    if "Value" not in text:
        continue

    match = re.search(
        r"/minifig/([^/]+)",
        href
    )

    if not match:
        continue

    code = match.group(1).strip()

    # BrickEconomy currently displays values in USD.
    price_match = re.search(
        r"Value\s+\$\s*([\d,.]+)",
        text
    )

    if not price_match:
        continue

    price_text = price_match.group(1)

    try:
        price = float(price_text.replace(",", ""))
    except ValueError:
        continue

    name = text

    if name.startswith(code):
        name = name[len(code):].strip()

    name = re.sub(
        r"\s+Value\s+\$[\d,.]+$",
        "",
        name
    ).strip()

    current[code] = {
        "name": name,
        "price": price,
    }


# Load yesterday's state.
if STATE_FILE.exists():
    previous = json.loads(STATE_FILE.read_text())
else:
    previous = {}


previous_items = previous.get("items", {})

# First run = baseline only.
first_run = not bool(previous_items)


if first_run:

    STATE_FILE.write_text(
        json.dumps(
            {"items": current},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )

    print(
        f"First scan completed. "
        f"Baseline saved for {len(current)} minifigs."
    )

    raise SystemExit(0)


# Compare lists.
current_codes = set(current.keys())
previous_codes = set(previous_items.keys())

added = sorted(current_codes - previous_codes)
removed = sorted(previous_codes - current_codes)


# Compare prices.
price_changes = []

for code in current_codes & previous_codes:

    old_price = previous_items[code].get("price")
    new_price = current[code]["price"]

    if not old_price or old_price <= 0:
        continue

    change = ((new_price - old_price) / old_price) * 100

    if abs(change) >= THRESHOLD:

        price_changes.append(
            (
                change,
                code,
                current[code]["name"],
                old_price,
                new_price,
            )
        )


gainers = sorted(
    [x for x in price_changes if x[0] >= THRESHOLD],
    reverse=True
)[:10]


losers = sorted(
    [x for x in price_changes if x[0] <= -THRESHOLD]
)[:10]


# No changes = no Discord message.
if not added and not removed and not gainers and not losers:

    STATE_FILE.write_text(
        json.dumps(
            {"items": current},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )

    print("No changes detected. No Discord message sent.")

    raise SystemExit(0)


def money(value):
    return f"${value:,.2f}"


message = [
    "🧱 **BrickEconomy — Daily Update**",
    f"**Retiring Soon:** {len(current):,} minifigs",
]


if added:

    message.append("")
    message.append("🟢 **ADDED — Retiring Soon**")

    for code in added:

        item = current[code]

        message.append(
            f"• `{code}` {item['name']} — "
            f"{money(item['price'])}"
        )


if removed:

    message.append("")
    message.append("🔴 **REMOVED — no longer Retiring Soon**")

    for code in removed:

        item = previous_items[code]

        message.append(
            f"• `{code}` {item['name']}"
        )


if gainers:

    message.append("")
    message.append("📈 **Price increases ≥ +5%**")

    for change, code, name, old_price, new_price in gainers:

        message.append(
            f"• `{code}` {name} — "
            f"**+{change:.2f}%** "
            f"({money(old_price)} → {money(new_price)})"
        )


if losers:

    message.append("")
    message.append("📉 **Price decreases ≤ -5%**")

    for change, code, name, old_price, new_price in losers:

        message.append(
            f"• `{code}` {name} — "
            f"**{change:.2f}%** "
            f"({money(old_price)} → {money(new_price)})"
        )


discord_response = requests.post(
    DISCORD_WEBHOOK,
    json={
        "content": "\n".join(message),
        "allowed_mentions": {
            "parse": []
        },
    },
    timeout=30,
)

discord_response.raise_for_status()


# Save today's state.
STATE_FILE.write_text(
    json.dumps(
        {"items": current},
        ensure_ascii=False,
        separators=(",", ":"),
    )
)


print(
    f"Scan complete: {len(current)} minifigs | "
    f"added: {len(added)} | "
    f"removed: {len(removed)} | "
    f"price changes: {len(price_changes)}"
)
