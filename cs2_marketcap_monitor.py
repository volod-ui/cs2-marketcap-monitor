import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SOURCE_URL = "https://cs2cap.com/cs2-market-cap"
STATE_FILE = Path("cs2_marketcap_state.json")
REPORT_HOURS = {2, 10, 18}
DAILY_24H_HOUR = 10
BRUSSELS = ZoneInfo("Europe/Brussels")
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_CSMARKET"]
FORCE_RUN = os.environ.get("FORCE_RUN", "false").lower() == "true"

def fetch_market_cap():
    response = requests.get(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; CS2-Market-Monitor/1.0)"}, timeout=60)
    response.raise_for_status()
    html = response.text
    cleaned = re.sub(r"<[^>]+>", " ", html)
    cleaned = " ".join(cleaned.split())
    match = re.search(r"Total market cap +[$]([0-9]+(?:[.][0-9]+)?)([KMBT])", cleaned, re.IGNORECASE)
    if not match:
        match = re.search(r"Total market cap.{0,1500}?[$]([0-9]+(?:[.][0-9]+)?)([KMBT])", html, re.IGNORECASE | re.DOTALL)
    if not match:
        raise RuntimeError("Could not find CS2 market cap on the CS2Cap page.")
    value = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[suffix]
    return value * multiplier

def load_state():
    if not STATE_FILE.exists():
        return {"snapshots": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"snapshots": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")

def find_snapshot_at_or_before(snapshots, target_time):
    candidates = []
    for snapshot in snapshots:
        try:
            timestamp = datetime.fromisoformat(snapshot["timestamp"])
            if timestamp <= target_time:
                candidates.append((timestamp, snapshot))
        except (KeyError, TypeError, ValueError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None

def percent_change(current, previous):
    if previous is None or previous == 0:
        return None
    return ((current - previous) / previous) * 100

def format_cap(value):
    if value >= 1_000_000_000:
        return "${:.3f}B".format(value / 1_000_000_000)
    if value >= 1_000_000:
        return "${:.2f}M".format(value / 1_000_000)
    if value >= 1_000:
        return "${:.1f}K".format(value / 1_000)
    return "${:,.0f}".format(value)

def send_discord(message):
    response = requests.post(DISCORD_WEBHOOK, json={"content": message, "allowed_mentions": {"parse": []}}, timeout=30)
    response.raise_for_status()

def build_message(now, current, previous_8h, previous_24h):
    change_8h = percent_change(current, previous_8h["market_cap"] if previous_8h else None)
    change_24h = percent_change(current, previous_24h["market_cap"] if previous_24h else None)
    lines = ["📊 **CS2 MARKET CAP UPDATE**", "🕐 {} Brussels".format(now.strftime("%d-%m-%Y %H:%M")), "", "💰 **Market cap:** {}".format(format_cap(current))]
    if change_8h is not None:
        arrow = "🟢" if change_8h >= 0 else "🔴"
        lines.append("{} **8u:** {:+.2f}% vs {}".format(arrow, change_8h, format_cap(previous_8h["market_cap"])))
    else:
        lines.append("⏳ **8u:** nog geen vorige meting beschikbaar")
    if now.hour == DAILY_24H_HOUR:
        if change_24h is not None:
            arrow = "🟢" if change_24h >= 0 else "🔴"
            lines.append("{} **24u:** {:+.2f}% vs {}".format(arrow, change_24h, format_cap(previous_24h["market_cap"])))
        else:
            lines.append("⏳ **24u:** nog geen meting van 24 uur geleden")
    lines.extend(["", "Bron: CS2Cap market-cap tracker."])
    return chr(10).join(lines)

def main():
    now = datetime.now(BRUSSELS)
    print("Brussels time:", now.strftime("%Y-%m-%d %H:%M:%S %Z"))
    if not FORCE_RUN and now.hour not in REPORT_HOURS:
        print("Outside CS2 market-cap report hours. No scan performed.")
        return
    current = fetch_market_cap()
    print("Current CS2 market cap:", format_cap(current))
    state = load_state()
    snapshots = state["snapshots"]
    previous_8h = find_snapshot_at_or_before(snapshots, now - timedelta(hours=8))
    previous_24h = find_snapshot_at_or_before(snapshots, now - timedelta(hours=24))
    snapshots.append({"timestamp": now.isoformat(), "market_cap": current})
    snapshots.sort(key=lambda item: item.get("timestamp", ""))
    cutoff = now - timedelta(days=3)
    kept = []
    for item in snapshots:
        try:
            if datetime.fromisoformat(item["timestamp"]) >= cutoff:
                kept.append(item)
        except (KeyError, TypeError, ValueError):
            continue
    state["snapshots"] = kept
    save_state(state)
    send_discord(build_message(now, current, previous_8h, previous_24h))
    print("CS2 market-cap Discord update sent.")

if __name__ == "__main__":
    main()