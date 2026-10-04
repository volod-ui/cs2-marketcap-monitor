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

PRICE_URL = (
    CMC_BASE
    + "/v2/simple/price"
)

MARKETCAP_URL = (
    CMC_BASE
    + "/v1/global-metrics/quotes/latest"
)

COINS_FILE = Path(
    "crypto_coins.json"
)

STATE_FILE = Path(
    "crypto_state.json"
)

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK_CRYPTO"
]

EVENT_NAME = os.environ.get(
    "GITHUB_EVENT_NAME",
    "schedule"
)

THRESHOLD = 0.0

BRUSSELS = ZoneInfo(
    "Europe/Brussels"
)


# =========================================================
# SPECIAL CMC LOOKUPS
# =========================================================
# CMC symbols are not guaranteed to be unique.
#
# BABY = Babylon
# W    = Wormhole
#
# These two are deliberately queried by slug.

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
                headers={
                    "Accept": "application/json"
                },
                timeout=30,
            )

            if response.status_code == 429:

                if attempt < tries - 1:

                    wait = 2 ** attempt

                    print(
                        f"CMC rate limited us. "
                        f"Waiting {wait}s..."
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


# =========================================================
# LOAD COIN LIST
# =========================================================

coin_config = load_json(
    COINS_FILE,
    {"coins": []},
)

symbols = [
    str(symbol).upper()
    for symbol in coin_config.get(
        "coins",
        []
    )
]

if not symbols:

    raise RuntimeError(
        "crypto_coins.json contains no coins."
    )


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
        "marketcap": None,
        "marketcap_slot": None,
        "prices": {},
        "price_slot": None,
    },
)


# =========================================================
# DETERMINE DUE JOBS
# =========================================================
#
# We schedule the GitHub Action around the DST change:
#
# Summer:
#   02:00 UTC = 04:00 Brussels
#   14:00 UTC = 16:00 Brussels
#
# Winter:
#   03:00 UTC = 04:00 Brussels
#   15:00 UTC = 16:00 Brussels
#
# The workflow runs on both possible UTC hours and this
# code decides whether the Brussels slot is due.
#
# We also allow a delayed run to execute during the next
# hour, while the slot ID prevents duplicates.


def current_slot_for(
    target_hour
):

    if (
        now.hour in
        (target_hour, target_hour + 1)
    ):

        slot_date = now.date()

        return (
            f"{slot_date.isoformat()}-"
            f"{target_hour:02d}"
        )

    return None


marketcap_slot = None

if now.hour in (4, 5):

    marketcap_slot = (
        f"{now.date().isoformat()}-04"
    )

elif now.hour in (16, 17):

    marketcap_slot = (
        f"{now.date().isoformat()}-16"
    )


price_slot = None

if now.hour in (4, 5):

    price_slot = (
        f"{now.date().isoformat()}-04"
    )


# =========================================================
# TEST MODE
# =========================================================
#
# When manually running the workflow with test mode,
# fetch live data and send a test message, but DO NOT
# change the saved baseline.
#
# This allows us to test CMC + Discord safely.
# =========================================================

if EVENT_NAME == "workflow_dispatch":

    test_mode = (
        os.environ.get(
            "CRYPTO_TEST_MODE",
            "false"
        ).lower()
        == "true"
    )

else:

    test_mode = False


# =========================================================
# FETCH PRICES
# =========================================================

def fetch_prices():

    regular_symbols = [
        symbol
        for symbol in symbols
        if symbol not in SPECIAL_SLUGS
    ]

    prices = {}

    # -----------------------------------------------------
    # Normal symbols
    # -----------------------------------------------------

    if regular_symbols:

        response = get_json(
            PRICE_URL,
            {
                "symbol": ",".join(
                    regular_symbols
                ),
                "convert": "EUR",
                "skip_invalid": "true",
            },
        )

        for item in response.get(
            "data",
            []
        ):

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()

            quotes = item.get(
                "quotes",
                []
            )

            if not quotes:
                continue

            quote = quotes[0]

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
                "price": float(price),
            }


    # -----------------------------------------------------
    # Exact slug lookups
    # -----------------------------------------------------

    for symbol, slug in SPECIAL_SLUGS.items():

        if symbol not in symbols:
            continue

        response = get_json(
            PRICE_URL,
            {
                "slug": slug,
                "convert": "EUR",
            },
        )

        for item in response.get(
            "data",
            []
        ):

            actual_symbol = str(
                item.get(
                    "symbol",
                    symbol
                )
            ).upper()

            quotes = item.get(
                "quotes",
                []
            )

            if not quotes:
                continue

            quote = quotes[0]

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
                "price": float(price),
            }

            break


    missing = [
        symbol
        for symbol in symbols
        if symbol not in prices
    ]

    if missing:

        raise RuntimeError(
            "CMC did not return prices for: "
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
# TEST RUN
# =========================================================

if test_mode:

    live_prices = fetch_prices()

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
            f"{len(live_prices)}/{len(symbols)}"
        ),
        "",
        "✅ CoinMarketCap connection working.",
        "✅ Discord webhook connected.",
        "",
        "**Tracked:** "
        + ", ".join(symbols),
    ]

    response = requests.post(
        DISCORD_WEBHOOK,
        json={
            "content": "\n".join(
                message
            ),
            "allowed_mentions": {
                "parse": []
            },
        },
        timeout=30,
    )

    response.raise_for_status()

    print(
        "Test completed successfully."
    )

    raise SystemExit(0)


# =========================================================
# DO NOTHING IF NOT A SCHEDULED SLOT
# =========================================================

if not marketcap_slot and not price_slot:

    print(
        "No crypto job is due right now."
    )

    raise SystemExit(0)


# =========================================================
# MARKET CAP — EVERY 12 HOURS
# =========================================================

if (
    marketcap_slot
    and state.get(
        "marketcap_slot"
    ) != marketcap_slot
):

    current_marketcap = (
        fetch_marketcap()
    )

    previous_marketcap = state.get(
        "marketcap"
    )

    marketcap_change = percent_change(
        previous_marketcap,
        current_marketcap,
    )


    # -----------------------------------------------------
    # First official slot = baseline only
    # -----------------------------------------------------

    if previous_marketcap is None:

        print(
            "Creating first market-cap baseline."
        )

        state["marketcap"] = (
            current_marketcap
        )

        state["marketcap_slot"] = (
            marketcap_slot
        )

    else:

        message = [
            "🌐 **CRYPTO MARKET CAP — 12H**",
            "",
            (
                f"**Total market cap:** "
                f"{format_money(current_marketcap)}"
            ),
            (
                f"**Since previous measurement:** "
                f"{marketcap_change:+.2f}%"
            ),
            "",
            (
                f"🕓 "
                f"{now.strftime('%d-%m-%Y %H:%M')} "
                f"Brussels"
            ),
        ]


        response = requests.post(
            DISCORD_WEBHOOK,
            json={
                "content": "\n".join(
                    message
                ),
                "allowed_mentions": {
                    "parse": []
                },
            },
            timeout=30,
        )

        response.raise_for_status()


        state["marketcap"] = (
            current_marketcap
        )

        state["marketcap_slot"] = (
            marketcap_slot
        )

        print(
            "Market-cap notification sent."
        )


# =========================================================
# COIN PRICES — EVERY DAY AT 04:00
# =========================================================

if (
    price_slot
    and state.get(
        "price_slot"
    ) != price_slot
):

    current_prices = fetch_prices()

    previous_prices = state.get(
        "prices",
        {}
    )


    # -----------------------------------------------------
    # First official 04:00 = baseline only
    # -----------------------------------------------------

    if not previous_prices:

        print(
            "Creating first daily price baseline."
        )

        state["prices"] = (
            current_prices
        )

        state["price_slot"] = (
            price_slot
        )

    else:

        gainers = []
        losers = []

        unchanged = []


        for symbol in symbols:

            current = current_prices[
                symbol
            ]

            previous = previous_prices.get(
                symbol
            )

            if not previous:

                continue

            old_price = previous.get(
                "price"
            )

            new_price = current.get(
                "price"
            )

            change = percent_change(
                old_price,
                new_price,
            )

            if change is None:

                continue

            entry = {
                "symbol": symbol,
                "name": current["name"],
                "change": change,
                "old_price": old_price,
                "new_price": new_price,
            }

            if change > 0:

                gainers.append(
                    entry
                )

            elif change < 0:

                losers.append(
                    entry
                )

            else:

                unchanged.append(
                    entry
                )


        gainers.sort(
            key=lambda x: x["change"],
            reverse=True
        )

        losers.sort(
            key=lambda x: x["change"]
        )


        message = [
            "💰 **CRYPTO — DAILY 04:00**",
            "",
            (
                f"**Tracked coins:** "
                f"{len(current_prices)}/{len(symbols)}"
            ),
        ]


        # -------------------------------------------------
        # Gainers
        # -------------------------------------------------

        if gainers:

            message.append("")
            message.append(
                "📈 **GAINERS**"
            )

            for item in gainers:

                message.append(
                    f"• **{item['symbol']}** "
                    f"{item['change']:+.2f}% "
                    f"("
                    f"{format_price(item['old_price'])}"
                    f" → "
                    f"{format_price(item['new_price'])}"
                    f")"
                )


        # -------------------------------------------------
        # Losers
        # -------------------------------------------------

        if losers:

            message.append("")
            message.append(
                "📉 **LOSERS**"
            )

            for item in losers:

                message.append(
                    f"• **{item['symbol']}** "
                    f"{item['change']:+.2f}% "
                    f"("
                    f"{format_price(item['old_price'])}"
                    f" → "
                    f"{format_price(item['new_price'])}"
                    f")"
                )


        # -------------------------------------------------
        # Discord size protection
        # -------------------------------------------------

        full_message = "\n".join(
            message
        )

        chunk_size = 1900


        chunks = []

        while len(full_message) > chunk_size:

            split_at = full_message.rfind(
                "\n",
                0,
                chunk_size
            )

            if split_at < 500:

                split_at = chunk_size

            chunks.append(
                full_message[:split_at]
            )

            full_message = (
                full_message[
                    split_at:
                ].lstrip()
            )


        if full_message:

            chunks.append(
                full_message
            )


        for chunk in chunks:

            response = requests.post(
                DISCORD_WEBHOOK,
                json={
                    "content": chunk,
                    "allowed_mentions": {
                        "parse": []
                    },
                },
                timeout=30,
            )

            response.raise_for_status()


        state["prices"] = (
            current_prices
        )

        state["price_slot"] = (
            price_slot
        )

        print(
            "Daily crypto price notification sent."
        )


# =========================================================
# SAVE STATE
# =========================================================

save_json(
    STATE_FILE,
    state
)

print(
    "Crypto monitor finished successfully."
)
