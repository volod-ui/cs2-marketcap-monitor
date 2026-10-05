import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


API_URL = "https://api.pricempire.com/v4/trader/items/prices"
APP_ID = 730
SOURCE = "steam"
CURRENCY = "USD"

MIN_PRICE_USD = 2.0
MIN_LIQUIDITY = 85.0
MIN_TRADES_7D = 50
MIN_LISTINGS = 15

TOP_N = 10
REPORT_HOURS = {2, 10, 18}

BRUSSELS = ZoneInfo("Europe/Brussels")

API_KEY = os.environ["PRICEMPIRE_API_KEY"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_CSMARKET"]

FORCE_RUN = (
    os.environ.get("FORCE_RUN", "false").lower() == "true"
)


def fetch_items():
    response = requests.get(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Accept": "application/json",
        },
        params={
            "app_id": APP_ID,
            "sources": SOURCE,
            "currency": CURRENCY,
            "avg": "true",
            "median": "false",
        },
        timeout=90,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Pricempire API returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            "Unexpected Pricempire response format: "
            f"{type(data).__name__}"
        )

    return data


def get_steam_price(item):
    prices = item.get("prices") or []

    for price in prices:
        if str(price.get("provider_key", "")).lower() == SOURCE:
            return price

    return None


def build_candidates(items):
    candidates = []
    stats = {
        "received": len(items),
        "with_steam_price": 0,
        "passed_price": 0,
        "passed_liquidity": 0,
        "passed_trades": 0,
        "passed_listings": 0,
        "passed_all": 0,
    }

    for item in items:
        steam = get_steam_price(item)

        if not steam:
            continue

        stats["with_steam_price"] += 1

        price_cents = steam.get("price")
        avg_7_cents = steam.get("avg_7")

        if price_cents is None or avg_7_cents is None:
            continue

        try:
            price = float(price_cents) / 100
            avg_7 = float(avg_7_cents) / 100
            liquidity = float(item.get("liquidity", 0) or 0)
            trades_7d = int(float(item.get("trades_7d", 0) or 0))
            listings = int(float(steam.get("count", 0) or 0))
        except (TypeError, ValueError):
            continue

        if price < MIN_PRICE_USD:
            continue
        stats["passed_price"] += 1

        if liquidity > 0 and liquidity < MIN_LIQUIDITY:
            continue
        if liquidity > 0:
            stats["passed_liquidity"] += 1

        if trades_7d > 0 and trades_7d < MIN_TRADES_7D:
            continue
        if trades_7d > 0:
            stats["passed_trades"] += 1

        if listings > 0 and listings < MIN_LISTINGS:
            continue
        if listings > 0:
            stats["passed_listings"] += 1

        if avg_7 <= 0:
            continue

        change = ((price - avg_7) / avg_7) * 100

        candidates.append(
            {
                "name": item.get(
                    "market_hash_name",
                    "Unknown item",
                ),
                "price": price,
                "avg_7": avg_7,
                "change": change,
                "liquidity": liquidity,
                "trades_7d": trades_7d,
                "listings": listings,
            }
        )

    stats["passed_all"] = len(candidates)
    return candidates, stats


def money(value):
    if value >= 1000:
        return f"€{value:,.0f}"
    if value >= 1:
        return f"€{value:,.2f}"
    return f"€{value:,.4f}"


def send_discord(message):
    response = requests.post(
        DISCORD_WEBHOOK,
        json={
            "content": message,
            "allowed_mentions": {"parse": []},
        },
        timeout=30,
    )
    response.raise_for_status()


def build_message(gainers, losers, now, stats):
    lines = [
        "🎮 **CS2 STEAM MARKET — 8U METING**",
        f"🕐 {now.strftime('%d-%m-%Y %H:%M')} Brussels",
        "",
        (
            f"Filters: ≥${MIN_PRICE_USD:.0f} | "
            f"Liquidity ≥{MIN_LIQUIDITY:.0f} | "
            f"Trades 7d ≥{MIN_TRADES_7D} | "
            f"Listings ≥{MIN_LISTINGS}"
        ),
        "",
        "📈 **TOP 10 STIJGERS**",
        "",
    ]

    if gainers:
        for index, item in enumerate(gainers, 1):
            lines.append(
                f"**{index}. {item['name']}** "
                f"**+{item['change']:.2f}%**"
            )
            lines.append(
                f"${item['price']:.2f} "
                f"(7d gem. ${item['avg_7']:.2f}) · "
                f"Liq {item['liquidity']:.0f} · "
                f"Trades {item['trades_7d']} · "
                f"Listings {item['listings']}"
            )
            lines.append("")
    else:
        lines.append("Geen stijgers gevonden.")
        lines.append("")

    lines.extend(
        [
            "📉 **TOP 10 DALERS**",
            "",
        ]
    )

    if losers:
        for index, item in enumerate(losers, 1):
            lines.append(
                f"**{index}. {item['name']}** "
                f"**{item['change']:.2f}%**"
            )
            lines.append(
                f"${item['price']:.2f} "
                f"(7d gem. ${item['avg_7']}:.2f}) · "
                f"Liq {item['liquidity']:.0f} · "
                f"Trades {item['trades_7d']} · "
                f"Listings {item['listings']}"
            )
            lines.append("")
    else:
        lines.append("Geen dalers gevonden.")
        lines.append("")

    lines.extend(
        [
            (
                f"📊 {stats['passed_all']} items "
                "voldeden aan alle filters."
            ),
            (
                "ℹ️ Beweging = huidige Steam-prijs "
                "vs. Pricempire 7-daags gemiddelde in USD."
            ),
        ]
    )

    return "\n".join(lines)


def main():
    now = datetime.now(BRUSSELS)

    print(
        "Brussels time:",
        now.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )

    if not FORCE_RUN and now.hour not in REPORT_HOURS:
        print(
            "Outside CS2 report hours. "
            "No API scan performed."
        )
        return

    print("Fetching Pricempire Steam CS2 data...")
    items = fetch_items()

    candidates, stats = build_candidates(items)

    gainers = sorted(
        [item for item in candidates if item["change"] > 0],
        key=lambda item: item["change"],
        reverse=True,
    )[:TOP_N]

    losers = sorted(
        [item for item in candidates if item["change"] < 0],
        key=lambda item: item["change"],
    )[:TOP_N]

    message = build_message(
        gainers,
        losers,
        now,
        stats,
    )

    send_discord(message)

    print(
        f"Discord report sent: "
        f"{len(gainers)} gainers, {len(losers)} losers."
    )


if __name__ == "__main__":
    main()
