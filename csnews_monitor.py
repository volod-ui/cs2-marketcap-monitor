import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# =========================================================
# CONFIGURATION
# =========================================================

CMC_BASE = "https://pro-api.coinmarketcap.com/public-api"

PRICE_URL = CMC_BASE + "/v2/simple/price"

MARKETCAP_URL = (
    CMC_BASE
    + "/v1/global-metrics/quotes/latest"
)

COINS_FILE = Path("crypto_coins.json")
WATCHLIST_FILE = Path("crypto_watchlist.json")
STATE_FILE = Path("crypto_state.json")

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK_CRYPTO"
]

EVENT_NAME = os.environ.get(
    "GITHUB_EVENT_NAME",
    "schedule"
)

TEST_MODE = (
    EVENT_NAME == "workflow_dispatch"
    and os.environ.get(
        "CRYPTO_TEST_MODE",
        "false"
    ).lower() == "true"
)

BRUSSELS = ZoneInfo(
    "Europe/Brussels"
)

THRESHOLD = 5.0

STRONG_THRESHOLD = 10.0


# =========================================================
# SPECIAL CMC LOOKUPS
# =========================================================
#
# Symbols are not always unique on CMC.
# These coins are therefore pinned by CMC slug.
#
# BABY  = Babylon
# W     = Wormhole
# WLFI  = World Liberty Financial
# POL   = Polygon Ecosystem Token
# ATH   = Aethir
# DOG   = Dog (Bitcoin / Runes)
#
# =========================================================

SPECIAL_SLUGS = {
    "BABY": "babylon",
    "W": "wormhole",
    "WLFI": "world-liberty-financial-wlfi",
    "POL": "polygon-ecosystem-token",
    "ATH": "aethir",
    "DOG": "dog-go-to-the-moon-rune",
}


# =========================================================
# API HELPERS
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

            if (
                response.status_code == 429
                and attempt < tries - 1
            ):
                wait = 2 ** attempt

                print(
                    "CMC rate limited us. "
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
                    f"CMC error {error_code}: "
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

    raise last_error


# =========================================================
# FILE HELPERS
# =========================================================

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


# =========================================================
# FORMATTING
# =========================================================

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
# DISCORD
# =========================================================

def send_discord(
    content,
):
    response = requests.post(
        DISCORD_WEBHOOK,
        json={
            "content": content,
            "allowed_mentions": {
                "parse": []
            },
        },
        timeout=30,
    )

    response.raise_for_status()


def send_chunks(
    lines,
):
    text = "\n".join(lines)

    chunks = []

    while len(text) > 1900:

        split_at = text.rfind(
            "\n",
            0,
            1900
        )

        if split_at < 500:
            split_at = 1900

        chunks.append(
            text[:split_at]
        )

        text = (
            text[split_at:]
            .lstrip()
        )

    if text:
        chunks.append(text)

    for chunk in chunks:
        send_discord(chunk)


# =========================================================
# LOAD COIN LISTS
# =========================================================

portfolio_config = load_json(
    COINS_FILE,
    {"coins": []},
)

watchlist_config = load_json(
    WATCHLIST_FILE,
    {"coins": []},
)

portfolio_symbols = [
    str(symbol).upper()
    for symbol in portfolio_config.get(
        "coins",
        []
    )
]

watchlist_symbols = [
    str(symbol).upper()
    for symbol in watchlist_config.get(
        "coins",
        []
    )
]

if not portfolio_symbols:
    raise RuntimeError(
        "crypto_coins.json contains no coins."
    )

if not watchlist_symbols:
    raise RuntimeError(
        "crypto_watchlist.json contains no coins."
    )


all_symbols = list(
    dict.fromkeys(
        portfolio_symbols
        + watchlist_symbols
    )
)


# =========================================================
# CURRENT BRUSSELS TIME
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
    {},
)

state.setdefault(
    "marketcap",
    {}
)

state.setdefault(
    "portfolio",
    {}
)

state.setdefault(
    "watchlist",
    {}
)

state.setdefault(
    "marketcap_slot",
    None
)

state.setdefault(
    "portfolio_slot",
    None
)

state.setdefault(
    "watchlist_slot",
    None
)


# =========================================================
# DAILY 04:00 SLOT
# =========================================================
#
# 04:00 Brussels can be:
# Summer: 02:00 UTC
# Winter: 03:00 UTC
#
# We also accept 05:00 Brussels so a delayed GitHub
# Action can still perform the same daily measurement.
#
# =========================================================

slot = None

if now.hour in (4, 5):
    slot = (
        f"{now.date().isoformat()}-04"
    )


# =========================================================
# FETCH ALL COIN PRICES
# =========================================================

def fetch_prices():

    regular_symbols = [
        symbol
        for symbol in all_symbols
        if symbol not in SPECIAL_SLUGS
    ]

    prices = {}

    # -----------------------------------------------------
    # Regular symbol lookups
    # -----------------------------------------------------

    if regular_symbols:

        payload = get_json(
            PRICE_URL,
            {
                "symbol": ",".join(
                    regular_symbols
                ),
                "convert": "EUR",
                "skip_invalid": "true",
                "include_market_cap": "true",
                "include_24h_volume": "true",
                "include_24h_change": "true",
                "include_last_updated": "true",
            },
        )

        for item in payload.get(
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
                "price": float(
                    price
                ),
                "cmc_24h": (
                    float(
                        quote[
                            "percent_change_24h"
                        ]
                    )
                    if quote.get(
                        "percent_change_24h"
                    ) is not None
                    else None
                ),
            }


    # -----------------------------------------------------
    # Exact slug lookups
    # -----------------------------------------------------

    for symbol, slug in SPECIAL_SLUGS.items():

        if symbol not in all_symbols:
            continue

        payload = get_json(
            PRICE_URL,
            {
                "slug": slug,
                "convert": "EUR",
                "include_market_cap": "true",
                "include_24h_volume": "true",
                "include_24h_change": "true",
                "include_last_updated": "true",
            },
        )

        for item in payload.get(
            "data",
            []
        ):

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
                "price": float(
                    price
                ),
                "cmc_24h": (
                    float(
                        quote[
                            "percent_change_24h"
                        ]
                    )
                    if quote.get(
                        "percent_change_24h"
                    ) is not None
                    else None
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
            "CMC did not return prices for: "
            + ", ".join(missing)
        )

    return prices


# =========================================================
# FETCH TOTAL MARKET CAP
# =========================================================

def fetch_marketcap():

    payload = get_json(
        MARKETCAP_URL,
        {
            "convert": "EUR"
        },
    )

    eur_quote = (
        payload
        .get("data", {})
        .get("quote", {})
        .get("EUR", {})
    )

    value = eur_quote.get(
        "total_market_cap"
    )

    if value is None:
        raise RuntimeError(
            "CMC did not return "
            "EUR total market cap."
        )

    return float(value)


# =========================================================
# TEST MODE
# =========================================================

if TEST_MODE:

    live_prices = fetch_prices()

    live_marketcap = fetch_marketcap()

    send_discord(
        "🧪 **CRYPTO MONITOR — TEST**\n\n"
        "✅ CoinMarketCap connection working.\n"
        "✅ Discord webhook connected.\n\n"
        f"**Portfolio:** "
        f"{len(portfolio_symbols)} coins\n"
        f"**Wantlist:** "
        f"{len(watchlist_symbols)} coins\n"
        f"**Prices returned:** "
        f"{len(live_prices)}/{len(all_symbols)}\n"
        f"**Total market cap:** "
        f"{format_money(live_marketcap)}\n"
        "**Live schedule:** "
        "daily 04:00 Brussels\n\n"
        "No saved history was changed."
    )

    print(
        "Test completed successfully."
    )

    raise SystemExit(0)


# =========================================================
# NOTHING TO DO OUTSIDE DAILY SLOT
# =========================================================

if not slot:

    print(
        "No crypto job is due right now."
    )

    raise SystemExit(0)


# =========================================================
# FETCH CURRENT PRICES
# =========================================================

current_prices = fetch_prices()


# =========================================================
# TOTAL CRYPTO MARKET CAP
# DAILY 04:00 — SEPARATE DISCORD MESSAGE
# =========================================================

if state.get(
    "marketcap_slot"
) != slot:

    current_marketcap = (
        fetch_marketcap()
    )

    previous_marketcap = (
        state
        .get("marketcap", {})
        .get("value")
    )

    if previous_marketcap is None:

        print(
            "Creating first market-cap baseline."
        )

    else:

        marketcap_change = percent_change(
            previous_marketcap,
            current_marketcap,
        )

        send_chunks([
            "🌐 **TOTAL CRYPTO MARKET CAP — DAILY 04:00**",
            "",
            (
                f"**Current:** "
                f"{format_money(current_marketcap)}"
            ),
            (
                f"**Previous 04:00:** "
                f"{format_money(previous_marketcap)}"
            ),
            (
                f"**04:00 → 04:00:** "
                f"{marketcap_change:+.2f}%"
            ),
            "",
            (
                f"🕓 "
                f"{now.strftime('%d-%m-%Y %H:%M')} "
                f"Brussels"
            ),
        ])

    state["marketcap"] = {
        "value": current_marketcap,
        "timestamp": now.isoformat(),
    }

    state["marketcap_slot"] = slot


# =========================================================
# PORTFOLIO — DAILY 04:00
# =========================================================

if state.get(
    "portfolio_slot"
) != slot:

    previous_portfolio = state.get(
        "portfolio",
        {}
    )

    # -----------------------------------------------------
    # First scan = baseline only
    # -----------------------------------------------------

    if not previous_portfolio:

        print(
            "Creating first portfolio baseline."
        )

    else:

        entries = []

        for symbol in portfolio_symbols:

            current = current_prices[
                symbol
            ]

            previous = previous_portfolio.get(
                symbol
            )

            if not previous:
                continue

            own_change = percent_change(
                previous.get("price"),
                current["price"],
            )

            if own_change is None:
                continue

            entries.append({
                "symbol": symbol,
                "price": current["price"],
                "old_price": previous[
                    "price"
                ],
                "own_change": own_change,
                "cmc_24h": current.get(
                    "cmc_24h"
                ),
            })


        # Strongest movement first
        entries.sort(
            key=lambda item: item[
                "own_change"
            ],
            reverse=True
        )


        lines = [
            "💰 **CRYPTO PORTFOLIO — DAILY 04:00**",
            "",
            (
                f"**Portfolio:** "
                f"{len(portfolio_symbols)} coins"
            ),
            (
                "**CMC 24h** = rolling CMC movement"
            ),
            (
                "**04:00 → 04:00** = "
                "our own daily measurement"
            ),
            "",
        ]


        for item in entries:

            own = item[
                "own_change"
            ]

            cmc = item[
                "cmc_24h"
            ]

            if own >= THRESHOLD:
                marker = "🟢"

            elif own <= -THRESHOLD:
                marker = "🔴"

            else:
                marker = "•"

            if cmc is None:
                cmc_text = "n/a"
            else:
                cmc_text = (
                    f"{cmc:+.2f}%"
                )

            lines.append(
                f"{marker} **{item['symbol']}** | "
                f"CMC 24h: {cmc_text} | "
                f"04:00→04:00: "
                f"{own:+.2f}% | "
                f"{format_price(item['old_price'])} "
                f"→ "
                f"{format_price(item['price'])}"
            )


        send_chunks(lines)


    # -----------------------------------------------------
    # Save today's portfolio baseline
    # -----------------------------------------------------

    state["portfolio"] = {
        symbol: {
            "price": current_prices[
                symbol
            ]["price"],
            "name": current_prices[
                symbol
            ]["name"],
            "cmc_24h": current_prices[
                symbol
            ].get("cmc_24h"),
        }
        for symbol in portfolio_symbols
    }

    state["portfolio_slot"] = slot


# =========================================================
# WANTLIST — DAILY 04:00
# =========================================================
#
# Alert if:
#   CMC 24h <= -5%
# OR
#   own 04:00 -> 04:00 <= -5%
#
# Double Drop:
#   BOTH <= -5%
#
# Strong Double Drop:
#   BOTH <= -10%
#
# No Discord message when nothing reaches -5%.
#
# =========================================================

if state.get(
    "watchlist_slot"
) != slot:

    previous_watchlist = state.get(
        "watchlist",
        {}
    )

    alerts = []


    # -----------------------------------------------------
    # First scan = baseline only
    # -----------------------------------------------------

    if not previous_watchlist:

        print(
            "Creating first watchlist baseline."
        )

    else:

        for symbol in watchlist_symbols:

            current = current_prices[
                symbol
            ]

            previous = previous_watchlist.get(
                symbol
            )

            if not previous:
                continue

            own_change = percent_change(
                previous.get("price"),
                current["price"],
            )

            cmc_change = current.get(
                "cmc_24h"
            )

            if own_change is None:
                continue


            own_drop = (
                own_change
                <= -THRESHOLD
            )

            cmc_drop = (
                cmc_change is not None
                and cmc_change
                <= -THRESHOLD
            )


            # At least one measurement must
            # show a decline of 5% or more.
            if not own_drop and not cmc_drop:
                continue


            double_drop = (
                own_drop
                and cmc_drop
            )


            strong_double_drop = (
                double_drop
                and own_change
                <= -STRONG_THRESHOLD
                and cmc_change
                <= -STRONG_THRESHOLD
            )


            alerts.append({
                "symbol": symbol,
                "price": current[
                    "price"
                ],
                "old_price": previous[
                    "price"
                ],
                "own_change": own_change,
                "cmc_24h": cmc_change,
                "double_drop": double_drop,
                "strong_double_drop": (
                    strong_double_drop
                ),
            })


        # Worst decline first
        alerts.sort(
            key=lambda item: min(
                item["own_change"],
                (
                    item["cmc_24h"]
                    if item["cmc_24h"]
                    is not None
                    else 999.0
                ),
            )
        )


        if alerts:

            lines = [
                "🛒 **CRYPTO WANTLIST — BUYING WATCH**",
                "",
                (
                    "🔻 Showing coins with at least "
                    "one decline of **-5% or more**"
                ),
                (
                    "**CMC 24h** = rolling CMC movement"
                ),
                (
                    "**04:00 → 04:00** = "
                    "our own daily measurement"
                ),
                "",
            ]


            for item in alerts:

                if item[
                    "strong_double_drop"
                ]:

                    label = (
                        "🔥 **STRONG DOUBLE DROP**"
                    )

                elif item[
                    "double_drop"
                ]:

                    label = (
                        "🔴 **DOUBLE DROP**"
                    )

                else:

                    label = (
                        "🟠 **DROP**"
                    )


                if item[
                    "cmc_24h"
                ] is None:

                    cmc_text = "n/a"

                else:

                    cmc_text = (
                        f"{item['cmc_24h']:+.2f}%"
                    )


                lines.append(
                    f"{label} — "
                    f"**{item['symbol']}** "
                    f"{format_price(item['price'])} | "
                    f"CMC 24h: {cmc_text} | "
                    f"04:00→04:00: "
                    f"{item['own_change']:+.2f}% | "
                    f"{format_price(item['old_price'])} "
                    f"→ "
                    f"{format_price(item['price'])}"
                )


            send_chunks(lines)

        else:

            print(
                "No watchlist alert: "
                "no coin dropped 5% or more."
            )


    # -----------------------------------------------------
    # Save today's watchlist baseline
    # -----------------------------------------------------

    state["watchlist"] = {
        symbol: {
            "price": current_prices[
                symbol
            ]["price"],
            "name": current_prices[
                symbol
            ]["name"],
            "cmc_24h": current_prices[
                symbol
            ].get("cmc_24h"),
        }
        for symbol in watchlist_symbols
    }

    state["watchlist_slot"] = slot


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
