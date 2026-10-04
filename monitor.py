import json
import os
from pathlib import Path

import requests


# =========================================================
# CONFIGURATION
# =========================================================

API_URL = (
    "https://api.pricempire.com/v4/trader/items/prices"
)

STATE_FILE = Path("state.json")

THRESHOLD = 10.0

SOURCE = "buff163"

# Quality filters.
MIN_LIQUIDITY = 80.0
MIN_TRADES_7D = 10
MIN_LISTINGS = 1

APP_ID = 730

CURRENCY = "USD"


# =========================================================
# ENVIRONMENT
# =========================================================

API_KEY = os.environ[
    "PRICEMPIRE_API_KEY"
]

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK"
]


# =========================================================
# LOAD PREVIOUS STATE
# =========================================================

if STATE_FILE.exists():

    try:

        previous = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except (
        json.JSONDecodeError,
        OSError,
    ):

        previous = {}

else:

    previous = {}


previous_prices = previous.get(
    "prices",
    {}
)


# =========================================================
# FETCH PRICEMPIRE DATA
# =========================================================
#
# We explicitly request the metadata needed for
# liquidity / volume filtering.
#
# =========================================================

response = requests.get(
    API_URL,
    headers={
        "Authorization":
            f"Bearer {API_KEY}",
        "Accept":
            "application/json",
    },
    params={
        "app_id": APP_ID,
        "currency": CURRENCY,
        "sources": SOURCE,
        "metas": (
            "liquidity,"
            "trades_7d,"
            "count"
        ),
    },
    timeout=90,
)

response.raise_for_status()

items = response.json()


if not isinstance(
    items,
    list,
):

    raise RuntimeError(
        "Pricempire returned an unexpected response format."
    )


# =========================================================
# PARSE + QUALITY FILTER
# =========================================================

current_prices = {}

qualified_items = 0

filtered_liquidity = 0

filtered_volume = 0

filtered_listings = 0

filtered_zero_price = 0


for item in items:

    name = item.get(
        "market_hash_name"
    )

    if not name:
        continue


    # -----------------------------------------------------
    # Quality metadata
    # -----------------------------------------------------

    try:

        liquidity = float(
            item.get(
                "liquidity",
                0
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        liquidity = 0.0


    try:

        trades_7d = int(
            float(
                item.get(
                    "trades_7d",
                    0
                )
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        trades_7d = 0


    try:

        listing_count = int(
            float(
                item.get(
                    "count",
                    0
                )
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        listing_count = 0


    # -----------------------------------------------------
    # FILTER 1 — LIQUIDITY
    # -----------------------------------------------------

    if liquidity < MIN_LIQUIDITY:

        filtered_liquidity += 1

        continue


    # -----------------------------------------------------
    # FILTER 2 — 7-DAY TRADE VOLUME
    # -----------------------------------------------------

    if trades_7d < MIN_TRADES_7D:

        filtered_volume += 1

        continue


    # -----------------------------------------------------
    # FILTER 3 — REAL LISTING COUNT
    # -----------------------------------------------------

    if listing_count < MIN_LISTINGS:

        filtered_listings += 1

        continue


    # -----------------------------------------------------
    # FIND BUFF163 PRICE
    # -----------------------------------------------------

    buff_price = None

    for price_row in item.get(
        "prices",
        []
    ):

        if (
            price_row.get(
                "provider_key"
            )
            != SOURCE
        ):
            continue


        price = price_row.get(
            "price"
        )

        if price is None:
            continue


        try:

            price = float(price)

        except (
            TypeError,
            ValueError,
        ):

            continue


        # Never accept zero / negative prices.
        if price <= 0:

            filtered_zero_price += 1

            buff_price = None

            break


        buff_price = price

        break


    if buff_price is None:

        continue


    # -----------------------------------------------------
    # QUALIFIED ITEM
    # -----------------------------------------------------

    current_prices[name] = {
        "price": buff_price,
        "liquidity": liquidity,
        "trades_7d": trades_7d,
        "count": listing_count,
    }

    qualified_items += 1


# =========================================================
# FIND PRICE MOVERS
# =========================================================

movers = []


for name, current in current_prices.items():

    old = previous_prices.get(
        name
    )

    if old is None:
        continue


    # State compatibility:
    # Old state may contain a simple number.
    if isinstance(
        old,
        dict,
    ):

        old_price = old.get(
            "price"
        )

    else:

        old_price = old


    if old_price is None:
        continue


    try:

        old_price = float(
            old_price
        )

    except (
        TypeError,
        ValueError,
    ):

        continue


    if old_price <= 0:
        continue


    change = (
        (
            current["price"]
            - old_price
        )
        / old_price
    ) * 100


    if abs(change) < THRESHOLD:
        continue


    movers.append(
        {
            "name": name,
            "change": change,
            "price": current[
                "price"
            ],
            "old_price": old_price,
            "liquidity": current[
                "liquidity"
            ],
            "trades_7d": current[
                "trades_7d"
            ],
            "count": current[
                "count"
            ],
        }
    )


# =========================================================
# SORT MOVERS
# =========================================================

gainers = sorted(
    [
        item
        for item in movers
        if item["change"]
        >= THRESHOLD
    ],
    key=lambda item: item[
        "change"
    ],
    reverse=True,
)[:10]


losers = sorted(
    [
        item
        for item in movers
        if item["change"]
        <= -THRESHOLD
    ],
    key=lambda item: item[
        "change"
    ],
)[:10]


# =========================================================
# DISCORD FORMAT
# =========================================================

def money(
    value
):

    return f"${value / 100:,.2f}"


lines = [
    "📊 **CS2 PRICE MONITOR — 8h SCAN**",
    "",
    (
        f"**Liquid items monitored:** "
        f"{qualified_items:,}"
    ),
    (
        f"**Filter:** liquidity ≥ "
        f"{MIN_LIQUIDITY:.0f} | "
        f"≥ {MIN_TRADES_7D} trades / 7d"
    ),
    (
        f"**Source:** {SOURCE}"
    ),
]


# =========================================================
# GAINERS
# =========================================================

if gainers:

    lines.extend(
        [
            "",
            "🚀 **GAINERS ≥ +10%**",
        ]
    )

    for item in gainers:

        lines.append(
            (
                f"• `{item['name']}` — "
                f"**{item['change']:+.2f}%** "
                f"("
                f"{money(item['old_price'])}"
                f" → "
                f"{money(item['price'])}"
                f")"
            )
        )


# =========================================================
# LOSERS
# =========================================================

if losers:

    lines.extend(
        [
            "",
            "🔻 **LOSERS ≤ -10%**",
        ]
    )

    for item in losers:

        lines.append(
            (
                f"• `{item['name']}` — "
                f"**{item['change']:+.2f}%** "
                f"("
                f"{money(item['old_price'])}"
                f" → "
                f"{money(item['price'])}"
                f")"
            )
        )


# =========================================================
# NO MOVERS
# =========================================================

if not gainers and not losers:

    lines.extend(
        [
            "",
            "✅ **Geen significante bewegingen.**",
            "",
            (
                "Geen Discord-alert voor "
                "prijsbewegingen."
            ),
        ]
    )


# =========================================================
# SEND DISCORD
# =========================================================

message = "\n".join(
    lines
)


response = requests.post(
    DISCORD_WEBHOOK,
    json={
        "content": message,
        "allowed_mentions": {
            "parse": []
        },
    },
    timeout=30,
)

response.raise_for_status()


# =========================================================
# SAVE ONLY QUALIFIED ITEMS
# =========================================================
#
# This is important:
#
# The next 8h comparison is made only against items
# that pass the quality filters.
#
# =========================================================

state_to_save = {
    "prices": {
        name: {
            "price": data["price"],
            "liquidity": data["liquidity"],
            "trades_7d": data["trades_7d"],
            "count": data["count"],
        }
        for name, data
        in current_prices.items()
    }
}


STATE_FILE.write_text(
    json.dumps(
        state_to_save,
        separators=(",", ":")
    ),
    encoding="utf-8",
)


print(
    f"Items returned by Pricempire: "
    f"{len(items):,}"
)

print(
    f"Qualified liquid items: "
    f"{qualified_items:,}"
)

print(
    f"Filtered for liquidity: "
    f"{filtered_liquidity:,}"
)

print(
    f"Filtered for 7d volume: "
    f"{filtered_volume:,}"
)

print(
    f"Filtered for listings: "
    f"{filtered_listings:,}"
)

print(
    f"Qualified movers: "
    f"{len(movers)}"
)

print(
    "CS2 price monitor finished successfully."
)
