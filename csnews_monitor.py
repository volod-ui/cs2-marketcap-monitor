import json
import os
import re
from pathlib import Path

import requests


# ---------------------------------------------------------
# Settings
# ---------------------------------------------------------

API_URL = (
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


# ---------------------------------------------------------
# Steam API request
# ---------------------------------------------------------

params = {
    "appid": APP_ID,
    "count": 20,
    "maxlength": 100000,
    "feeds": "steam_community_announcements",
}


response = requests.get(
    API_URL,
    params=params,
    timeout=60,
)

response.raise_for_status()

data = response.json()


news_items = (
    data.get("appnews", {})
    .get("newsitems", [])
)


print(
    f"Steam returned {len(news_items)} "
    f"news items."
)


# ---------------------------------------------------------
# Only official CS2 update posts
# ---------------------------------------------------------

updates = []

for item in news_items:

    title = (
        item.get("title", "")
        .strip()
    )

    if not title.lower().startswith(
        "counter-strike 2 update"
    ):
        continue

    updates.append(item)


# Newest first.
updates.sort(
    key=lambda x: x.get("date", 0),
    reverse=True
)


if not updates:

    raise RuntimeError(
        "No official Counter-Strike 2 Update "
        "was found in the Steam feed."
    )


latest = updates[0]


print(
    f"Latest official update: "
    f"{latest.get('title')}"
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


last_gid = previous.get(
    "last_gid"
)


# ---------------------------------------------------------
# First run = baseline
# ---------------------------------------------------------

if not last_gid:

    STATE_FILE.write_text(
        json.dumps(
            {
                "last_gid": str(
                    latest.get("gid")
                )
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "First run completed."
    )

    print(
        "Latest update saved as baseline."
    )

    print(
        "No Discord message sent."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Find updates newer than last seen
# ---------------------------------------------------------

new_updates = []

for item in updates:

    gid = str(
        item.get("gid")
    )

    if gid == str(last_gid):

        break

    new_updates.append(item)


if not new_updates:

    print(
        "No new Counter-Strike 2 updates."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Clean Steam BBCode
# ---------------------------------------------------------

def clean_text(text):

    if not text:
        return ""

    # Convert common list markers.
    text = re.sub(
        r"\[\*\]",
        "• ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\[/?(?:list|olist)\]",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    # Headings.
    text = re.sub(
        r"\[h[1-6]\]\s*",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\[/h[1-6]\]",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    # URLs: [url=LINK]text[/url]
    text = re.sub(
        r"\[url=([^\]]+)\](.*?)\[/url\]",
        r"\2",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Remove preview/image/youtube tags.
    text = re.sub(
        r"\[(?:previewyoutube|img|video)[^\]]*\].*?"
        r"\[/(?:previewyoutube|img|video)\]",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Remove remaining BBCode tags.
    text = re.sub(
        r"\[[^\]]+\]",
        "",
        text,
    )

    # Basic formatting.
    text = text.replace(
        "\r",
        ""
    )

    # Collapse excessive blank lines.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    # Trim whitespace.
    text = text.strip()

    return text


# ---------------------------------------------------------
# Convert timestamp
# ---------------------------------------------------------

from datetime import datetime, timezone


def format_date(timestamp):

    try:

        dt = datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc,
        )

        return dt.strftime(
            "%d %B %Y"
        )

    except (TypeError, ValueError):

        return ""


# ---------------------------------------------------------
# Split Discord messages
# ---------------------------------------------------------

def send_discord_message(
    content
):

    # Discord normal message limit.
    chunk_size = 1900

    chunks = []

    while len(content) > chunk_size:

        split_at = content.rfind(
            "\n",
            0,
            chunk_size
        )

        if split_at < 500:

            split_at = chunk_size

        chunks.append(
            content[:split_at]
        )

        content = content[
            split_at:
        ].lstrip()

    if content:

        chunks.append(
            content
        )

    for chunk in chunks:

        r = requests.post(
            DISCORD_WEBHOOK,
            json={
                "content": chunk,
                "allowed_mentions": {
                    "parse": []
                },
            },
            timeout=30,
        )

        r.raise_for_status()


# ---------------------------------------------------------
# Process new updates
# ---------------------------------------------------------

for update in reversed(
    new_updates
):

    title = update.get(
        "title",
        "Counter-Strike 2 Update"
    )

    date = format_date(
        update.get("date")
    )

    url = update.get(
        "url",
        "https://store.steampowered.com/news/app/730/"
    )

    content = clean_text(
        update.get(
            "contents",
            ""
        )
    )

    message = [
        "📰 **COUNTER-STRIKE 2 UPDATE**",
        "",
        f"**{date}**",
        "",
        content,
        "",
        f"🔗 {url}",
    ]

    send_discord_message(
        "\n".join(message)
    )

    print(
        f"Sent update: {title}"
    )


# ---------------------------------------------------------
# Save latest update
# ---------------------------------------------------------

STATE_FILE.write_text(
    json.dumps(
        {
            "last_gid": str(
                latest.get("gid")
            )
        },
        indent=2,
    ),
    encoding="utf-8",
)


print(
    f"Processed {len(new_updates)} "
    f"new Counter-Strike 2 update(s)."
)
