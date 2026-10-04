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


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# Download BrickEconomy page
# ---------------------------------------------------------

response = requests.get(
    URL,
    headers=HEADERS,
    timeout=60,
)

response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")


# ---------------------------------------------------------
# Read current Retiring Soon list
# ---------------------------------------------------------

current = {}

for link in soup.find_all("a", href=True):

    href = link.get("href", "")
    text = " ".join(link.stripped_strings)

    # We only want individual minifig pages.
    if not href.startswith("/minifig/"):
        continue

    # These entries contain the current BrickEconomy value.
    if "Value" not in text:
        continue

    match = re.search(
        r"/minifig/([^/]+)",
        href
    )

    if not match:
        continue

    code = match.group(1).strip()

    # BrickEconomy currently displays EUR values here.
    price_match = re.search(
        r"Value\s+€\s*([\d,.]+)",
        text
    )

    if not price_match:
        continue

    price_text = price_match.group(1)

    try:
        # Current BrickEconomy format is e.g. €79.91.
        price = float(price_text.replace(",", ""))
    except ValueError:
        continue

    # Remove the minifig code from the start.
    name = text

    if name.startswith(code):
        name = name[len(code):].strip()

    # Remove the "Value €XX.XX" suffix.
    name = re.sub(
        r"\s+Value\s+€[\d,.]+$",
        "",
        name
    ).strip()

    current[code] = {
        "name": name,
        "price": price,
    }


# ---------------------------------------------------------
# Safety check
# ---------------------------------------------------------
# Never overwrite a good state with an empty scrape.
# This protects us if BrickEconomy is temporarily blocked
# or changes its HTML.

if len(current) == 0:

    raise RuntimeError(
        "BrickEconomy returned 0 minifigs. "
        "State was NOT changed."
    )


print(
    f"Current BrickEconomy list: "
    f"{len(current)} minifigs"
)


# ---------------------------------------------------------
# Load previous state
# ---------------------------------------------------------

if STATE_FILE.exists():

    previous = json.loads(
        STATE_FILE.read_text(
            encoding="utf-8"
        )
    )

else:

    previous = {}


previous_items = previous.get(
    "items",
    {}
)


# ---------------------------------------------------------
# FIRST RUN
# ---------------------------------------------------------
# The first successful run only creates a baseline.
# It does NOT send hundreds of "new" notifications.

if not previous_items:

    STATE_FILE.write_text(
        json.dumps(
            {
                "items": current
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(
        "First scan completed. "
        "Baseline saved. No Discord message sent."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Detect added / removed minifigs
# ---------------------------------------------------------

current_codes = set(current.keys())
previous_codes = set(previous_items.keys())

added = sorted(
    current_codes - previous_codes
)

removed = sorted(
    previous_codes - current_codes
)


# ---------------------------------------------------------
# Detect price changes >= +5% or <= -5%
# ---------------------------------------------------------

price_changes = []

for code in current_codes & previous_codes:

    old_price = previous_items[code].get(
        "price"
    )

    new_price = current[code]["price"]

    if not old_price or old_price <= 0:
        continue

    change = (
        (new_price - old_price)
        / old_price
    ) * 100

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


# Biggest increases first.
gainers = sorted(
    [
        x for x in price_changes
        if x[0] >= THRESHOLD
    ],
    reverse=True,
)[:15]


# Biggest decreases first.
losers = sorted(
    [
        x for x in price_changes
        if x[0] <= -THRESHOLD
    ]
)[:15]


# ---------------------------------------------------------
# Nothing changed
# ---------------------------------------------------------

if (
    not added
    and not removed
    and not gainers
    and not losers
):

    STATE_FILE.write_text(
        json.dumps(
            {
                "items": current
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(
        "No changes detected. "
        "No Discord message sent."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Formatting
# ---------------------------------------------------------

def money(value):
    return f"€{value:,.2f}"


message = [
    "🧱 **BrickEconomy — Daily Update**",
    "",
    f"**Retiring Soon:** {len(current):,} minifigs",
]


# ---------------------------------------------------------
# Added
# ---------------------------------------------------------

if added:

    message.append("")
    message.append(
        f"🟢 **ADDED — {len(added)} minifig(s)**"
    )

    for code in added:

        item = current[code]

        message.append(
            f"• `{code}` {item['name']} — "
            f"{money(item['price'])}"
        )


# ---------------------------------------------------------
# Removed
# ---------------------------------------------------------

if removed:

    message.append("")
    message.append(
        f"🔴 **REMOVED — {len(removed)} minifig(s)**"
    )

    for code in removed:

        item = previous_items[code]

        message.append(
            f"• `{code}` {item['name']}"
        )


# ---------------------------------------------------------
# Price increases
# ---------------------------------------------------------

if gainers:

    message.append("")
    message.append(
        "📈 **Price increases ≥ +5%**"
    )

    for (
        change,
        code,
        name,
        old_price,
        new_price,
    ) in gainers:

        message.append(
            f"• `{code}` {name} — "
            f"**+{change:.2f}%** "
            f"({money(old_price)} → "
            f"{money(new_price)})"
        )


# ---------------------------------------------------------
# Price decreases
# ---------------------------------------------------------

if losers:

    message.append("")
    message.append(
        "📉 **Price decreases ≤ -5%**"
    )

    for (
        change,
        code,
        name,
        old_price,
        new_price,
    ) in losers:

        message.append(
            f"• `{code}` {name} — "
            f"**{change:.2f}%** "
            f"({money(old_price)} → "
            f"{money(new_price)})"
        )


# ---------------------------------------------------------
# Send Discord notification
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# Save today's state
# ---------------------------------------------------------

STATE_FILE.write_text(
    json.dumps(
        {
            "items": current
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ),
    encoding="utf-8",
)


print(
    f"Scan complete | "
    f"minifigs: {len(current)} | "
    f"added: {len(added)} | "
    f"removed: {len(removed)} | "
    f"price changes: {len(price_changes)}"
)
