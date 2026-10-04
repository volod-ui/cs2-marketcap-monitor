import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# =========================================================
# CONFIGURATION
# =========================================================

NEWS_URL = (
    "https://api.steampowered.com/"
    "ISteamNews/GetNewsForApp/v2/"
)

APP_ID = 730

STATE_FILE = Path(
    "csnews_state.json"
)

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK_CSNEWS"
]

BRUSSELS = ZoneInfo(
    "Europe/Brussels"
)


# =========================================================
# HELPERS
# =========================================================

def load_state():
    if not STATE_FILE.exists():
        return {}

    with STATE_FILE.open(
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def save_state(
    state,
):
    with STATE_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


def clean_steam_text(
    text,
):
    if not text:
        return ""

    # Remove Steam BBCode tags.
    text = re.sub(
        r"\[/?[^\]]+\]",
        "",
        text,
    )

    # Convert common HTML entities.
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )

    # Normalize whitespace.
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


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
    content,
):
    max_length = 1900

    while len(content) > max_length:

        split_at = content.rfind(
            "\n",
            0,
            max_length,
        )

        if split_at < 500:
            split_at = max_length

        send_discord(
            content[:split_at]
        )

        content = (
            content[split_at:]
            .lstrip()
        )

    if content:
        send_discord(content)


# =========================================================
# FETCH OFFICIAL STEAM NEWS
# =========================================================

response = requests.get(
    NEWS_URL,
    params={
        "appid": APP_ID,
        "count": 50,
        "maxlength": 10000,
        "feeds": "steam_community_announcements",
    },
    headers={
        "Accept": "application/json"
    },
    timeout=30,
)

response.raise_for_status()

payload = response.json()

news_items = (
    payload
    .get("appnews", {})
    .get("newsitems", [])
)

if not news_items:
    raise RuntimeError(
        "Steam returned no CS2 news items."
    )


# =========================================================
# LOAD STATE
# =========================================================

state = load_state()

previous_gid = state.get(
    "last_gid"
)


# =========================================================
# FIRST RUN
# =========================================================
#
# On an empty state we only establish a baseline.
# No old CS2 updates are sent to Discord.
#
# =========================================================

if not previous_gid:

    newest_gid = str(
        news_items[0]["gid"]
    )

    state["last_gid"] = newest_gid

    save_state(state)

    print(
        "First CS2 News scan completed."
    )

    print(
        f"Baseline GID: {newest_gid}"
    )

    raise SystemExit(0)


# =========================================================
# FIND NEW ITEMS SINCE LAST SCAN
# =========================================================

new_items = []

for item in news_items:

    gid = str(
        item.get("gid", "")
    )

    if gid == previous_gid:
        break

    new_items.append(item)


# =========================================================
# PROCESS ONLY OFFICIAL CS2 UPDATE POSTS
# =========================================================

official_updates = []

for item in reversed(new_items):

    title = (
        item.get("title")
        or ""
    ).strip()

    title_lower = title.lower()

    # Only actual Counter-Strike 2 update posts.
    is_update = (
        "counter-strike 2 update" in title_lower
        or title_lower.startswith(
            "counter-strike 2 update"
        )
    )

    if not is_update:
        continue

    official_updates.append(item)


# =========================================================
# SEND NEW UPDATES
# =========================================================

for item in official_updates:

    title = (
        item.get("title")
        or "Counter-Strike 2 Update"
    ).strip()

    contents = clean_steam_text(
        item.get("contents")
        or ""
    )

    url = (
        item.get("url")
        or ""
    ).strip()

    published_timestamp = item.get(
        "date"
    )

    published_text = ""

    if published_timestamp:

        try:

            published_dt = (
                datetime.fromtimestamp(
                    int(
                        published_timestamp
                    ),
                    timezone.utc,
                )
                .astimezone(
                    BRUSSELS
                )
            )

            published_text = (
                published_dt.strftime(
                    "%d-%m-%Y %H:%M"
                )
                + " Brussels"
            )

        except (
            TypeError,
            ValueError,
            OSError,
        ):
            published_text = ""


    lines = [
        "🔔 **CS2 UPDATE — VALVE**",
        "",
        f"**{title}**",
    ]

    if published_text:
        lines.extend([
            f"🕓 {published_text}",
            "",
        ])

    if contents:
        lines.extend([
            contents,
            "",
        ])

    if url:
        lines.extend([
            f"🔗 {url}",
        ])

    message = "\n".join(
        lines
    ).strip()

    send_chunks(message)

    print(
        f"Sent CS2 update: {title}"
    )


# =========================================================
# UPDATE STATE
# =========================================================
#
# Always store the newest Steam item.
# This prevents the same announcement from being
# processed repeatedly.
#
# =========================================================

newest_gid = str(
    news_items[0]["gid"]
)

state["last_gid"] = newest_gid

save_state(state)

print(
    "CS2 News monitor finished successfully."
)

print(
    f"New Steam items checked: "
    f"{len(new_items)}"
)

print(
    f"New official CS2 updates sent: "
    f"{len(official_updates)}"
)
