import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# =========================================================
# CONFIGURATION
# =========================================================

CMC_BASE = "https://pro-api.coinmarketcap.com/public-api"

QUOTES_URL = (
    CMC_BASE
    + "/v3/cryptocurrency/quotes/latest"
)

MARKETCAP_URL = (
    CMC_BASE
    + "/v1/global-metrics/quotes/latest"
)

SWAPLIST_FILE = Path("crypto_swaplist.json")
WISHLIST_FILE = Path("crypto_watchlist.json")
STATE_FILE = Path("crypto_state.json")

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK_CRYPTO"
]

# Use CoinMarketCap's keyless public API.
# This restores the original setup: no CMC account or API key
# is required for the supported public endpoints.
CMC_HEADERS = {
    "Accept": "application/json",
}

EVENT_NAME = os.environ.get(
    "GITHUB_EVENT_NAME",
    "schedule"
)

BRUSSELS = ZoneInfo(
    "Europe/Brussels"
)

# Discord reports
TARGET_HOURS = {
    2,
    10,
    18,
}

# Silent snapshots happen on the other 4-hour runs.
SNAPSHOT_KEEP_HOURS = 72

TOP_MOVER_THRESHOLD = 5.0

WISHLIST_DROP_THRESHOLD = -5.0

WISHLIST_STRONG_THRESHOLD = -7.5

WISHLIST_DOUBLE_THRESHOLD = -10.0


# =========================================================
# SPECIAL CMC LOOKUPS
# =========================================================

SPECIAL_SLUGS = {
    "BABY": "babylon",
    "W": "wormhole",
}


# =========================================================
# GENERAL HELPERS
# =========================================================

def get_json(
    url,
    params,
    tries=5,
):

    last_error = None

    for attempt in range(tries):

        try:

            response = requests.get(
                url,
                params=params,
                headers=CMC_HEADERS,
                timeout=30,
            )

            if response.status_code == 429:

                if attempt < tries - 1:

                    retry_after = response.headers.get(
                        "Retry-After"
                    )

                    try:
                        wait = max(
                            60,
                            int(retry_after)
                        )
                    except (TypeError, ValueError):
                        wait = 60

                    print(
                        f"CMC rate limited us. "
                        f"Waiting {wait}s before retry..."
                    )

                    time.sleep(wait)

                    continue

            response.raise_for_status()

            payload = response.json()

            status = payload.get(
                "status",
                {}
            )

            error_code = str(
                status.get(
                    "error_code",
                    "0"
                )
            )

            if error_code != "0":

                raise RuntimeError(
                    "CMC error "
                    f"{error_code}: "
                    f"{status.get('error_message')}"
                )

            return payload

        except Exception as exc:

            last_error = exc

            if attempt < tries - 1:

                wait = 2 ** attempt

                print(
                    f"Request failed: {exc}"
                )

                print(
                    f"Retrying in {wait}s..."
                )

                time.sleep(wait)

            else:

                raise last_error


def load_json(
    path,
    default,
):

    if not path.exists():

        return default

    with path.open(
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


def save_json(
    path,
    data,
):

    with path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def format_money(
    value,
):

    if value >= 1_000_000_000_000:

        return (
            f"€{value / 1_000_000_000_000:.2f}T"
        )

    if value >= 1_000_000_000:

        return (
            f"€{value / 1_000_000_000:.2f}B"
        )

    if value >= 1_000_000:

        return (
            f"€{value / 1_000_000:.2f}M"
        )

    if value >= 1_000:

        return (
            f"€{value / 1_000:.2f}K"
        )

    return f"€{value:,.2f}"


def format_price(
    value,
):

    if value >= 1000:

        return f"€{value:,.0f}"

    if value >= 1:

        return f"€{value:,.2f}"

    if value >= 0.01:

        return f"€{value:,.4f}"

    if value >= 0.0001:

        return f"€{value:,.6f}"

    return f"€{value:.8f}"


def percent_change(
    old,
    new,
):

    if old is None or old <= 0:

        return None

    return (
        (new - old)
        / old
    ) * 100


def send_discord(
    message,
):

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


def send_discord_chunks(
    message,
):

    chunk_size = 1900

    chunks = []

    remaining = message

    while len(remaining) > chunk_size:

        split_at = remaining.rfind(
            "\n",
            0,
            chunk_size,
        )

        if split_at < 500:

            split_at = chunk_size

        chunks.append(
            remaining[:split_at]
        )

        remaining = (
            remaining[
                split_at:
            ].lstrip()
        )

    if remaining:

        chunks.append(
            remaining
        )

    for chunk in chunks:

        send_discord(chunk)


# =========================================================
# LOAD LISTS
# =========================================================

swap_config = load_json(
    SWAPLIST_FILE,
    {"coins": []},
)

wishlist_config = load_json(
    WISHLIST_FILE,
    {"coins": []},
)

swaplist = [
    str(symbol).upper()
    for symbol in swap_config.get(
        "coins",
        []
    )
]

wishlist = [
    str(symbol).upper()
    for symbol in wishlist_config.get(
        "coins",
        []
    )
]


if not swaplist:

    raise RuntimeError(
        "crypto_swaplist.json contains no swaplist coins."
    )


# Wishlist may be empty.
# This allows the user to remove all wishlist coins
# without breaking the monitor.


# =========================================================
# ALL COINS
# =========================================================

all_symbols = list(
    dict.fromkeys(
        swaplist + wishlist
    )
)

regular_symbols = [
    symbol
    for symbol in all_symbols
    if symbol not in SPECIAL_SLUGS
]


# =========================================================
# CURRENT TIME
# =========================================================

now = datetime.now(
    timezone.utc
).astimezone(
    BRUSSELS
)

print(
    "Current Brussels time:",
    now.strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )
)


# =========================================================
# LOAD STATE
# =========================================================

state = load_json(
    STATE_FILE,
    {
        "snapshots": [],
        "last_report_slot": None,
    },
)


if not isinstance(
    state.get("snapshots"),
    list,
):

    state["snapshots"] = []


# =========================================================
# FETCH CURRENT COIN QUOTES
# =========================================================

def fetch_quotes():

    prices = {}

    # -----------------------------------------------------
    # Normal symbols
    # -----------------------------------------------------

    if regular_symbols:

        response = get_json(
            QUOTES_URL,
            {
                "symbol": ",".join(
                    regular_symbols
                ),
                "convert": "EUR",
            },
        )

        data = response.get(
            "data",
            []
        )

        if isinstance(
            data,
            dict,
        ):

            data = list(
                data.values()
            )

        for item in data:

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()

            quote_list = item.get(
                "quote",
                []
            )

            if not quote_list:

                continue

            quote = None

            for candidate in quote_list:

                if str(
                    candidate.get(
                        "symbol",
                        ""
                    )
                ).upper() == "EUR":

                    quote = candidate

                    break

            if quote is None:

                quote = quote_list[0]

            price = quote.get(
                "price"
            )

            if price is None:

                continue

            prices[symbol] = {
                "name": item.get(
                    "name",
                    symbol
                ),
                "price": float(
                    price
                ),
                "change_1h": float(
                    quote.get(
                        "percent_change_1h",
                        0
                    )
                ),
                "change_24h": float(
                    quote.get(
                        "percent_change_24h",
                        0
                    )
                ),
            }


    # -----------------------------------------------------
    # Exact slug lookups
    # -----------------------------------------------------

    for symbol, slug in SPECIAL_SLUGS.items():

        if symbol not in all_symbols:

            continue

        response = get_json(
            QUOTES_URL,
            {
                "slug": slug,
                "convert": "EUR",
            },
        )

        data = response.get(
            "data",
            []
        )

        if isinstance(
            data,
            dict,
        ):

            data = list(
                data.values()
            )

        for item in data:

            quote_list = item.get(
                "quote",
                []
            )

            if not quote_list:

                continue

            quote = None

            for candidate in quote_list:

                if str(
                    candidate.get(
                        "symbol",
                        ""
                    )
                ).upper() == "EUR":

                    quote = candidate

                    break

            if quote is None:

                quote = quote_list[0]

            price = quote.get(
                "price"
            )

            if price is None:

                continue

            prices[symbol] = {
                "name": item.get(
                    "name",
                    symbol
                ),
                "price": float(
                    price
                ),
                "change_1h": float(
                    quote.get(
                        "percent_change_1h",
                        0
                    )
                ),
                "change_24h": float(
                    quote.get(
                        "percent_change_24h",
                        0
                    )
                ),
            }

            break


    missing = [
        symbol
        for symbol in all_symbols
        if symbol not in prices
    ]

    if missing:

        raise RuntimeError(
            "CMC did not return data for: "
            + ", ".join(missing)
        )

    return prices


# =========================================================
# FETCH GLOBAL MARKET CAP
# =========================================================

def fetch_marketcap():

    response = get_json(
        MARKETCAP_URL,
        {
            "convert": "EUR"
        },
    )

    data = response.get(
        "data",
        {}
    )

    quote = data.get(
        "quote",
        {}
    )

    eur = quote.get(
        "EUR",
        {}
    )

    value = eur.get(
        "total_market_cap"
    )

    if value is None:

        raise RuntimeError(
            "CMC did not return "
            "EUR total market cap."
        )

    return float(value)


# =========================================================
# FIND HISTORICAL SNAPSHOT
# =========================================================

def find_snapshot(
    snapshots,
    hours_ago,
    tolerance_minutes=90,
):

    if not snapshots:

        return None

    target = (
        now
        - timedelta(
            hours=hours_ago
        )
    )

    best = None
    best_difference = None

    for snapshot in snapshots:

        try:

            snapshot_time = datetime.fromisoformat(
                snapshot["timestamp"]
            )

        except Exception:

            continue

        difference = abs(
            (
                snapshot_time
                - target
            ).total_seconds()
        )

        if (
            difference
            > tolerance_minutes * 60
        ):

            continue

        if (
            best_difference is None
            or difference < best_difference
        ):

            best = snapshot
            best_difference = difference

    return best


# =========================================================
# TEST MODE
# =========================================================

test_mode = (
    EVENT_NAME == "workflow_dispatch"
    and os.environ.get(
        "CRYPTO_TEST_MODE",
        "false"
    ).lower() == "true"
)


if test_mode:

    live_prices = fetch_quotes()

    live_marketcap = fetch_marketcap()

    message = [
        "🧪 **CRYPTO MONITOR — TEST**",
        "",
        (
            f"**Total market cap:** "
            f"{format_money(live_marketcap)}"
        ),
        (
            f"**Coins returned:** "
            f"{len(live_prices)}/{len(all_symbols)}"
        ),
        "",
        "✅ CoinMarketCap connection working.",
        "✅ Discord webhook connected.",
        "",
        (
            f"**SWAPLIST:** "
            f"{len(swaplist)} coins"
        ),
        (
            f"**WISHLIST:** "
            f"{len(wishlist)} coins"
        ),
    ]

    send_discord(
        "\n".join(message)
    )

    print(
        "Test completed successfully."
    )

    raise SystemExit(0)


# =========================================================
# FETCH LIVE DATA
# =========================================================

current_prices = fetch_quotes()

current_marketcap = fetch_marketcap()


# =========================================================
# CREATE CURRENT SNAPSHOT
# =========================================================

current_snapshot = {
    "timestamp": now.isoformat(),
    "marketcap": current_marketcap,
    "prices": current_prices,
}


# =========================================================
# SAVE SNAPSHOT IN MEMORY
# =========================================================

state["snapshots"].append(
    current_snapshot
)


# Keep useful recent history.

cutoff = (
    now
    - timedelta(
        hours=SNAPSHOT_KEEP_HOURS
    )
)

clean_snapshots = []

for snapshot in state["snapshots"]:

    try:

        snapshot_time = datetime.fromisoformat(
            snapshot["timestamp"]
        )

    except Exception:

        continue

    if snapshot_time >= cutoff:

        clean_snapshots.append(
            snapshot
        )


state["snapshots"] = clean_snapshots


# =========================================================
# DETERMINE REPORT SLOT
# =========================================================

report_slot = None

if now.hour in TARGET_HOURS:

    report_slot = (
        f"{now.date().isoformat()}-"
        f"{now.hour:02d}"
    )


# =========================================================
# SILENT SNAPSHOT
# =========================================================

if report_slot is None:

    save_json(
        STATE_FILE,
        state,
    )

    print(
        "Silent snapshot saved. "
        "No Discord report is due."
    )

    raise SystemExit(0)


# =========================================================
# PREVENT DUPLICATE REPORTS
# =========================================================

if state.get(
    "last_report_slot"
) == report_slot:

    save_json(
        STATE_FILE,
        state,
    )

    print(
        "This report slot was already processed."
    )

    raise SystemExit(0)


# =========================================================
# HISTORICAL BASELINES
# =========================================================

historical_snapshots = (
    state["snapshots"][:-1]
)

snapshot_8h = find_snapshot(
    historical_snapshots,
    8,
)

snapshot_12h = find_snapshot(
    historical_snapshots,
    12,
)

snapshot_24h = find_snapshot(
    historical_snapshots,
    24,
)


# =========================================================
# 1. MARKET CAP
# =========================================================
#
# Display:
#
# Total market cap
# 24h = CMC market-cap measurement vs 24h ago
# 8h  = our previous measurement
#
# No 12h / 1h market-cap figures.
# =========================================================

marketcap_change_24h = None

if snapshot_24h:

    marketcap_change_24h = percent_change(
        snapshot_24h.get(
            "marketcap"
        ),
        current_marketcap,
    )


marketcap_change_8h = None

if snapshot_8h:

    marketcap_change_8h = percent_change(
        snapshot_8h.get(
            "marketcap"
        ),
        current_marketcap,
    )


marketcap_message = [
    "🌐 **CRYPTO MARKET CAP**",
    "",
    (
        f"Total market cap: "
        f"{format_money(current_marketcap)}"
    ),
]


if marketcap_change_24h is not None:

    marketcap_message.append(
        f"24h: {marketcap_change_24h:+.2f}%"
    )

else:

    marketcap_message.append(
        "24h: —"
    )


if marketcap_change_8h is not None:

    marketcap_message.append(
        f"8h: {marketcap_change_8h:+.2f}%"
    )

else:

    marketcap_message.append(
        "8h: —"
    )


send_discord(
    "\n".join(
        marketcap_message
    )
)


# =========================================================
# 2. SWAPLIST
# =========================================================

swap_entries = []

for symbol in swaplist:

    current = current_prices.get(
        symbol
    )

    if not current:

        continue

    old_8h = None

    if snapshot_8h:

        old_8h = (
            snapshot_8h
            .get("prices", {})
            .get(symbol)
        )

    old_12h = None

    if snapshot_12h:

        old_12h = (
            snapshot_12h
            .get("prices", {})
            .get(symbol)
        )

    change_8h = None

    if old_8h:

        change_8h = percent_change(
            old_8h.get("price"),
            current.get("price"),
        )

    change_12h = None

    if old_12h:

        change_12h = percent_change(
            old_12h.get("price"),
            current.get("price"),
        )

    entry = {
        "symbol": symbol,
        "name": current["name"],
        "price": current["price"],
        "change_1h": current["change_1h"],
        "change_24h": current["change_24h"],
        "change_8h": change_8h,
        "change_12h": change_12h,
        "old_8h_price": (
            old_8h.get("price")
            if old_8h
            else None
        ),
    }

    swap_entries.append(
        entry
    )


# =========================================================
# TOP MOVERS
# =========================================================

top_movers = [
    entry
    for entry in swap_entries
    if abs(
        entry["change_24h"]
    ) >= TOP_MOVER_THRESHOLD
]

top_movers.sort(
    key=lambda item: abs(
        item["change_24h"]
    ),
    reverse=True,
)


other_coins = [
    entry
    for entry in swap_entries
    if abs(
        entry["change_24h"]
    ) < TOP_MOVER_THRESHOLD
]

other_coins.sort(
    key=lambda item: item["change_24h"],
    reverse=True,
)


swap_message = [
    "🔀 **SWAPLIST**",
    "",
]


# ---------------------------------------------------------
# TOP MOVERS
# ---------------------------------------------------------

if top_movers:

    swap_message.extend(
        [
            "🚀 **TOP MOVERS (±5% of meer)**",
            "",
        ]
    )

    for item in top_movers:

        swap_message.append(
            f"**{item['symbol']}** "
            f"{item['change_24h']:+.2f}%"
        )

    swap_message.append("")


# ---------------------------------------------------------
# DETAILS
# ---------------------------------------------------------

for item in top_movers:

    swap_message.extend(
        [
            f"🪙 **{item['symbol']}**",
            "",
            (
                f"24h: "
                f"{item['change_24h']:+.2f}%"
            ),
        ]
    )

    if item["old_8h_price"] is not None:

        swap_message.append(
            (
                f"{format_price(item['old_8h_price'])}"
                f" → "
                f"{format_price(item['price'])}"
            )
        )

    else:

        swap_message.append(
            "prijs: — → "
            f"{format_price(item['price'])}"
        )

    if item["change_12h"] is not None:

        swap_message.append(
            f"12h: "
            f"{item['change_12h']:+.2f}%"
        )

    else:

        swap_message.append(
            "12h: —"
        )

    if item["change_8h"] is not None:

        swap_message.append(
            f"8h: "
            f"{item['change_8h']:+.2f}%"
        )

    else:

        swap_message.append(
            "8h: —"
        )

    swap_message.append(
        f"1h: "
        f"{item['change_1h']:+.2f}%"
    )

    swap_message.append("")


# ---------------------------------------------------------
# OTHER TRACKED COINS
# ---------------------------------------------------------

swap_message.extend(
    [
        "📋 **OTHER TRACKED COINS**",
        "",
    ]
)

for item in other_coins:

    swap_message.append(
        f"{item['symbol']} "
        f"{item['change_24h']:+.2f}%"
    )


send_discord_chunks(
    "\n".join(
        swap_message
    )
)


# =========================================================
# 3. WISHLIST
# =========================================================
#
# Only send when at least one wishlist coin
# has CMC 24h <= -5%.
#
# Double drop:
#
# 24h <= -10%
# AND
# 8h <= -10%
# =========================================================

wishlist_entries = []

for symbol in wishlist:

    current = current_prices.get(
        symbol
    )

    if not current:

        continue

    change_24h = current["change_24h"]

    if change_24h > WISHLIST_DROP_THRESHOLD:

        continue

    old_8h = None

    if snapshot_8h:

        old_8h = (
            snapshot_8h
            .get("prices", {})
            .get(symbol)
        )

    old_12h = None

    if snapshot_12h:

        old_12h = (
            snapshot_12h
            .get("prices", {})
            .get(symbol)
        )

    change_8h = None

    if old_8h:

        change_8h = percent_change(
            old_8h.get("price"),
            current.get("price"),
        )

    change_12h = None

    if old_12h:

        change_12h = percent_change(
            old_12h.get("price"),
            current.get("price"),
        )

    double_drop = (
        change_8h is not None
        and change_24h
        <= WISHLIST_DOUBLE_THRESHOLD
        and change_8h
        <= WISHLIST_DOUBLE_THRESHOLD
    )

    wishlist_entries.append(
        {
            "symbol": symbol,
            "name": current["name"],
            "price": current["price"],
            "change_1h": current["change_1h"],
            "change_24h": change_24h,
            "change_8h": change_8h,
            "change_12h": change_12h,
            "double_drop": double_drop,
        }
    )


# Strongest drops first.

wishlist_entries.sort(
    key=lambda item: item["change_24h"]
)


if wishlist_entries:

    wishlist_message = [
        "🛒 **WISHLIST ALERT**",
        "",
    ]

    # -----------------------------------------------------
    # DOUBLE DROPS
    # -----------------------------------------------------

    double_drops = [
        item
        for item in wishlist_entries
        if item["double_drop"]
    ]

    normal_drops = [
        item
        for item in wishlist_entries
        if not item["double_drop"]
    ]


    if double_drops:

        wishlist_message.extend(
            [
                "🔥 **STERKE DUBBELE DALING**",
                "",
            ]
        )

        for item in double_drops:

            wishlist_message.append(
                (
                    f"**{item['symbol']}** "
                    f"24h {item['change_24h']:+.2f}%"
                    f" | "
                    f"8h {item['change_8h']:+.2f}%"
                )
            )

        wishlist_message.append("")


    # -----------------------------------------------------
    # NORMAL DROPS
    # -----------------------------------------------------

    if normal_drops:

        wishlist_message.extend(
            [
                "📉 **WISHLIST DALINGEN**",
                "",
            ]
        )

        for item in normal_drops:

            if (
                item["change_24h"]
                <= WISHLIST_STRONG_THRESHOLD
            ):

                icon = "🔴"

            else:

                icon = "🟠"

            wishlist_message.append(
                (
                    f"{icon} **{item['symbol']}** "
                    f"{item['change_24h']:+.2f}%"
                )
            )

        wishlist_message.append("")


    # -----------------------------------------------------
    # DETAILS
    # -----------------------------------------------------

    wishlist_message.extend(
        [
            "📊 **DETAILS**",
            "",
        ]
    )

    for item in wishlist_entries:

        wishlist_message.extend(
            [
                f"🪙 **{item['symbol']}**",
                (
                    f"24h: "
                    f"{item['change_24h']:+.2f}%"
                ),
            ]
        )

        if item["change_12h"] is not None:

            wishlist_message.append(
                (
                    f"12h: "
                    f"{item['change_12h']:+.2f}%"
                )
            )

        else:

            wishlist_message.append(
                "12h: —"
            )

        if item["change_8h"] is not None:

            wishlist_message.append(
                (
                    f"8h: "
                    f"{item['change_8h']:+.2f}%"
                )
            )

        else:

            wishlist_message.append(
                "8h: —"
            )

        wishlist_message.append(
            (
                f"1h: "
                f"{item['change_1h']:+.2f}%"
            )
        )

        wishlist_message.append("")


    send_discord_chunks(
        "\n".join(
            wishlist_message
        )
    )

    print(
        f"Wishlist alert sent for "
        f"{len(wishlist_entries)} coin(s)."
    )

else:

    print(
        "No wishlist drop >= 5%. "
        "No wishlist Discord message sent."
    )


# =========================================================
# FINALIZE REPORT SLOT
# =========================================================

state["last_report_slot"] = (
    report_slot
)


# =========================================================
# SAVE STATE
# =========================================================

save_json(
    STATE_FILE,
    state,
)


print(
    "Crypto monitor finished successfully."
)
