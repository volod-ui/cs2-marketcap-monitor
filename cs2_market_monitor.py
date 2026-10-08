import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests


API_BASE_URL = "https://api.openskin.dev/v1"
MARKETPLACE = "steam"

MIN_PRICE_USD = 2.0
MIN_LIQUIDITY = 85
MIN_TRADES_7D = 50
MIN_LISTINGS = 15

TOP_N = 10
REPORT_HOURS = {2, 10, 18}
HISTORY_BATCH_SIZE = 500
HISTORY_REQUEST_DELAY_SECONDS = 0.2

BRUSSELS = ZoneInfo("Europe/Brussels")

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_CSMARKET"]

FORCE_RUN = os.environ.get("FORCE_RUN", "false").lower() == "true"


def openskin_get(path, params=None):
    response = requests.get(
        f"{API_BASE_URL}{path}",
        params=params,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenSkin API returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


def openskin_post(path, payload):
    response = requests.post(
        f"{API_BASE_URL}{path}",
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        },
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenSkin API returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    return response.json()


def fetch_all_prices():
    data = openskin_get("/prices/all")

    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        raise RuntimeError(
            "Unexpected OpenSkin /v1/prices/all response format."
        )

    return data["data"]


def get_steam_price(item_data):
    steam = item_data.get("steam") or {}

    ask = steam.get("ask")
    liquidity = steam.get("liquidity_score")

    if liquidity is None:
        metrics = item_data.get("metrics") or {}
        liquidity = (metrics.get("steam") or {}).get("liquidity_score")

    listings = steam.get("sell_order_count")

    try:
        ask = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        ask = None

    try:
        liquidity = float(liquidity) if liquidity is not None else None
    except (TypeError, ValueError):
        liquidity = None

    try:
        listings = int(listings) if listings is not None else None
    except (TypeError, ValueError):
        listings = None

    return ask, liquidity, listings


def select_candidates(all_prices):
    candidates = []
    stats = {
        "received": len(all_prices),
        "with_steam_price": 0,
        "passed_price": 0,
        "passed_liquidity": 0,
        "passed_listings": 0,
        "passed_all_pre_history": 0,
    }

    for name, item_data in all_prices.items():
        if not isinstance(item_data, dict):
            continue

        price, liquidity, listings = get_steam_price(item_data)

        if price is None:
            continue

        stats["with_steam_price"] += 1

        if price < MIN_PRICE_USD:
            continue
        stats["passed_price"] += 1

        if liquidity is not None and liquidity < MIN_LIQUIDITY:
            continue
        stats["passed_liquidity"] += 1

        if listings is not None and listings < MIN_LISTINGS:
            continue
        stats["passed_listings"] += 1

        candidates.append(
            {
                "name": name,
                "price": price,
                "liquidity": liquidity,
                "listings": listings,
            }
        )

    stats["passed_all_pre_history"] = len(candidates)
    return candidates, stats


def fetch_7d_history(candidates, now):
    end_date = now.astimezone(timezone.utc).date()
    start_date = end_date - timedelta(days=7)

    history_by_item = {}
    names = [item["name"] for item in candidates]

    for start in range(0, len(names), HISTORY_BATCH_SIZE):
        batch = names[start:start + HISTORY_BATCH_SIZE]

        payload = {
            "items": batch,
            "marketplace": MARKETPLACE,
            "interval": "daily",
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        }

        response = openskin_post("/history/batch", payload)
        data = response.get("data") if isinstance(response, dict) else None

        if not isinstance(data, dict):
            raise RuntimeError(
                "Unexpected OpenSkin /v1/history/batch response format."
            )

        history_by_item.update(data)

        processed = min(start + len(batch), len(names))
        print(
            f"Fetched Steam history for {processed}/{len(names)} items."
        )

        if processed < len(names):
            time.sleep(HISTORY_REQUEST_DELAY_SECONDS)

    return history_by_item


def build_candidates(candidates, history_by_item, stats):
    final_candidates = []

    stats["with_history"] = 0
    stats["with_price_history"] = 0
    stats["passed_trades"] = 0
    stats["passed_all"] = 0

    for item in candidates:
        points = history_by_item.get(item["name"]) or []

        if not points:
            continue

        stats["with_history"] += 1

        prices = []
        volumes = []

        for point in points:
            try:
                price = float(point.get("price"))
            except (TypeError, ValueError, AttributeError):
                continue

            if price > 0:
                prices.append(price)

            volume = point.get("volume")
            try:
                if volume is not None:
                    volumes.append(int(float(volume)))
            except (TypeError, ValueError):
                pass

        if not prices:
            continue

        stats["with_price_history"] += 1

        avg_7 = sum(prices) / len(prices)
        trades_7d = sum(volumes) if volumes else None

        if trades_7d is not None and trades_7d < MIN_TRADES_7D:
            continue
        stats["passed_trades"] += 1

        if avg_7 <= 0:
            continue

        change = ((item["price"] - avg_7) / avg_7) * 100

        final_candidates.append(
            {
                **item,
                "avg_7": avg_7,
                "change": change,
                "trades_7d": trades_7d,
            }
        )

    stats["passed_all"] = len(final_candidates)
    return final_candidates


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


def format_metric(value):
    if value is None:
        return "n/a"
    return f"{value:g}"


def price_line(item):
    return (
        "$"
        + f"{item['price']:.2f}"
        + " (7d gem. $"
        + f"{item['avg_7']:.2f}"
        + ") · "
        + f"Liq {format_metric(item['liquidity'])} · "
        + f"Trades 7d {format_metric(item['trades_7d'])} · "
        + f"Listings {format_metric(item['listings'])}"
    )


def build_message(gainers, losers, now, stats):
    lines = [
        "🎮 **CS2 STEAM MARKET — 8U METING**",
        f"🕐 {now.strftime('%d-%m-%Y %H:%M')} Brussels",
        "",
        (
            "Filters: $"
            + f"{MIN_PRICE_USD:.0f}"
            + f"+ | Liquidity ≥{MIN_LIQUIDITY} | "
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
                f"**{item['change']:+.2f}%**"
            )
            lines.append(price_line(item))
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
                f"**{item['change']:+.2f}%**"
            )
            lines.append(price_line(item))
            lines.append("")
    else:
        lines.append("Geen dalers gevonden.")
        lines.append("")

    lines.extend(
        [
            "📊 **FILTER-OVERZICHT**",
            "",
            f"1️⃣ Catalogus: **{stats['received']:,}** items",
            f"2️⃣ Steam-prijs beschikbaar: **{stats['with_steam_price']:,}**",
            f"3️⃣ Prijs ≥ ${MIN_PRICE_USD:.0f}: **{stats['passed_price']:,}**",
            f"4️⃣ Liquidity ≥ {MIN_LIQUIDITY}: **{stats['passed_liquidity']:,}**",
            f"5️⃣ Listings ≥ {MIN_LISTINGS}: **{stats['passed_listings']:,}**",
            f"6️⃣ 7d geschiedenis beschikbaar: **{stats['with_history']:,}**",
            f"7️⃣ Geldige historische prijzen: **{stats['with_price_history']:,}**",
            f"8️⃣ Trades 7d ≥ {MIN_TRADES_7D}: **{stats['passed_trades']:,}**",
            "",
            f"✅ **Eindresultaat: {stats['passed_all']:,} items**",
            "",
            (
                "ℹ️ Beweging = huidige Steam ask-prijs "
                "vs. het gemiddelde van de beschikbare dagelijkse "
                "Steam-prijzen over de laatste 7 dagen."
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

    print("Fetching OpenSkin Steam CS2 data...")
    all_prices = fetch_all_prices()

    candidates, stats = select_candidates(all_prices)

    print(
        f"OpenSkin catalog: {stats['received']} items; "
        f"{stats['passed_all_pre_history']} passed pre-history filters."
    )

    if not candidates:
        raise RuntimeError(
            "No CS2 items passed the Steam price/liquidity/listing filters."
        )

    history_by_item = fetch_7d_history(candidates, now)
    final_candidates = build_candidates(
        candidates,
        history_by_item,
        stats,
    )

    gainers = sorted(
        [item for item in final_candidates if item["change"] > 0],
        key=lambda item: item["change"],
        reverse=True,
    )[:TOP_N]

    losers = sorted(
        [item for item in final_candidates if item["change"] < 0],
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
