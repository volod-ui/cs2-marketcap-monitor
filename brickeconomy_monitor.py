import json
import os
import re
from pathlib import Path

import requests


# ---------------------------------------------------------
# Settings
# ---------------------------------------------------------

SOURCE_URL = (
    "https://www.brickeconomy.com/minifigs/retiring-soon"
)

READER_URL = (
    "https://r.jina.ai/"
    "https://www.brickeconomy.com/minifigs/retiring-soon"
)

STATE_FILE = Path("brickeconomy_state.json")

THRESHOLD = 5.0

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK_BRICKECONOMY"
]


# ---------------------------------------------------------
# Download page through Jina Reader
# ---------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0 Safari/537.36"
    ),
    "X-Engine": "browser",
    "X-Respond-With": "markdown",
    "X-Timeout": "30",
}


response = requests.get(
    READER_URL,
    headers=HEADERS,
    timeout=90,
)

response.raise_for_status()

page_text = response.text


print(
    f"Downloaded BrickEconomy page: "
    f"{len(page_text):,} characters"
)


# ---------------------------------------------------------
# Parse minifig links
# ---------------------------------------------------------

current = {}


link_pattern = re.compile(
    r'\[([^\]]+)\]'
    r'\((https?://www\.brickeconomy\.com/minifig/[^)\s]+)\)'
)


for match in link_pattern.finditer(page_text):

    label = match.group(1).strip()
    url = match.group(2).strip()


    # Extract minifig code from URL.
    code_match = re.search(
        r"/minifig/([^/)\s]+)",
        url
    )

    if not code_match:
        continue


    code = code_match.group(1).strip()


    # We only want entries with a current value.
    if "Value" not in label:
        continue


    # BrickEconomy may return different currencies depending
    # on the page/session. We support the common symbols.
    price_match = re.search(
        r"Value\s*([€$£])\s*([\d,.]+)",
        label
    )

    if not price_match:
        continue


    currency = price_match.group(1)
    price_text = price_match.group(2)


    try:

        price = float(
            price_text.replace(",", "")
        )

    except ValueError:

        continue


    # Remove "Value €XX.XX" / "$XX.XX" / "£XX.XX".
    name = re.sub(
        r"\s+Value\s*[€$£]\s*[\d,.]+\s*$",
        "",
        label
    ).strip()


    # Remove minifig code from the start.
    if name.startswith(code):

        name = name[len(code):].strip()


    if not name:
        name = code


    current[code] = {
        "name": name,
        "price": price,
        "currency": currency,
    }


# ---------------------------------------------------------
# Safety check
# ---------------------------------------------------------
# Never overwrite the previous state when the page could
# not be parsed correctly.

if len(current) == 0:

    preview = page_text[:1000].replace(
        "\n",
        " "
    )

    raise RuntimeError(
        "BrickEconomy page was downloaded, but "
        "0 minifigs could be parsed. "
        "State was NOT changed. "
        f"Preview: {preview}"
    )


print(
    f"Parsed {len(current):,} Retiring Soon minifigs."
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
# FIRST RUN = baseline only
# ---------------------------------------------------------

if not previous_items:

    STATE_FILE.write_text(
        json.dumps(
            {
                "source": SOURCE_URL,
                "items": current
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


    print(
        "First successful scan completed."
    )

    print(
        "Baseline saved."
    )

    print(
        "No Discord message sent."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Compare list
# ---------------------------------------------------------

current_codes = set(
    current.keys()
)

previous_codes = set(
    previous_items.keys()
)


added = sorted(
    current_codes - previous_codes
)

removed = sorted(
    previous_codes - current_codes
)


# ---------------------------------------------------------
# Compare prices
# ---------------------------------------------------------

price_changes = []


for code in (
    current_codes & previous_codes
):

    old_data = previous_items[code]

    old_price = old_data.get(
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
                current[code]["currency"],
            )
        )


# Biggest increases first.
gainers = sorted(
    [
        item
        for item in price_changes
        if item[0] >= THRESHOLD
    ],
    reverse=True,
)[:15]


# Biggest decreases first.
losers = sorted(
    [
        item
        for item in price_changes
        if item[0] <= -THRESHOLD
    ]
)[:15]


# ---------------------------------------------------------
# Save helper
# ---------------------------------------------------------

def save_state():

    STATE_FILE.write_text(
        json.dumps(
            {
                "source": SOURCE_URL,
                "items": current
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------
# Nothing changed = no Discord message
# ---------------------------------------------------------

if (
    not added
    and not removed
    and not gainers
    and not losers
):

    save_state()

    print(
        "No changes detected."
    )

    print(
        "No Discord message sent."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Formatting
# ---------------------------------------------------------

def money(
    value,
    currency
):

    return (
        f"{currency}{value:,.2f}"
    )


# ---------------------------------------------------------
# Build Discord message
# ---------------------------------------------------------

message = [

    "🧱 **BrickEconomy — Daily Update**",

    "",

    (
        f"**Retiring Soon:** "
        f"{len(current):,} minifigs"
    ),

]


# ---------------------------------------------------------
# Added
# ---------------------------------------------------------

if added:

    message.append("")

    message.append(
        f"🟢 **ADDED — "
        f"{len(added)} minifig(s)**"
    )


    for code in added:

        item = current[code]

        message.append(
            f"• `{code}` "
            f"{item['name']} — "
            f"{money(item['price'], item['currency'])}"
        )


# ---------------------------------------------------------
# Removed
# ---------------------------------------------------------

if removed:

    message.append("")

    message.append(
        f"🔴 **REMOVED — "
        f"{len(removed)} minifig(s)**"
    )


    for code in removed:

        item = previous_items[code]

        message.append(
            f"• `{code}` "
            f"{item['name']}"
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
        currency,
    ) in gainers:

        message.append(
            f"• `{code}` "
            f"{name} — "
            f"**+{change:.2f}%** "
            f"("
            f"{money(old_price, currency)}"
            f" → "
            f"{money(new_price, currency)}"
            f")"
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
        currency,
    ) in losers:

        message.append(
            f"• `{code}` "
            f"{name} — "
            f"**{change:.2f}%** "
            f"("
            f"{money(old_price, currency)}"
            f" → "
            f"{money(new_price, currency)}"
            f")"
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

save_state()


print(
    f"Scan complete | "
    f"minifigs: {len(current)} | "
    f"added: {len(added)} | "
    f"removed: {len(removed)} | "
    f"price changes: {len(price_changes)}"
)
