import json
from datetime import datetime
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


URL = "https://www.brickeconomy.com/minifigs/retiring-soon"

STATE_FILE = Path("brickeconomy_state.json")

THRESHOLD = 5.0

BRUSSELS = ZoneInfo("Europe/Brussels")
TARGET_HOURS = {2, 10, 18}

DISCORD_WEBHOOK = os.environ[
    "DISCORD_WEBHOOK_BRICKECONOMY"
]


# ---------------------------------------------------------
# Start real Chrome browser
# ---------------------------------------------------------

options = Options()

options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
options.add_argument(
    "--disable-blink-features=AutomationControlled"
)

options.add_argument(
    "--user-agent=Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)


driver = webdriver.Chrome(
    options=options
)


try:

    # Hide the webdriver flag.
    driver.execute_script(
        """
        Object.defineProperty(
            navigator,
            'webdriver',
            {
                get: () => undefined
            }
        );
        """
    )

    driver.get(URL)


    # Wait until minifig links are present.
    WebDriverWait(
        driver,
        30
    ).until(
        lambda d: len(
            d.find_elements(
                By.CSS_SELECTOR,
                "a[href*='/minifig/']"
            )
        ) > 20
    )


    links = driver.find_elements(
        By.CSS_SELECTOR,
        "a[href*='/minifig/']"
    )


    print(
        f"Found {len(links)} minifig links."
    )


    # -----------------------------------------------------
    # Parse current list
    # -----------------------------------------------------

    current = {}


    for link in links:

        href = link.get_attribute(
            "href"
        )

        text = link.text.strip()


        if not href:
            continue


        code_match = re.search(
            r"/minifig/([^/?#]+)",
            href
        )


        if not code_match:
            continue


        code = code_match.group(1).strip()


        # We only care about entries that have a value.
        if "Value" not in text:
            continue


        price_match = re.search(
            r"Value\s*([€$£])\s*([\d.,]+)",
            text
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


        name = text


        # Remove the trailing Value section.
        name = re.sub(
            r"\s+Value\s*[€$£]\s*[\d.,]+\s*$",
            "",
            name
        ).strip()


        # Some labels begin with the minifig code.
        if name.startswith(code):

            name = name[
                len(code):
            ].strip()


        if not name:

            name = code


        current[code] = {
            "name": name,
            "price": price,
            "currency": currency,
        }


finally:

    driver.quit()


# ---------------------------------------------------------
# Safety check
# ---------------------------------------------------------

if len(current) == 0:

    raise RuntimeError(
        "Chrome loaded BrickEconomy but "
        "no minifigs could be parsed. "
        "State was NOT changed."
    )


print(
    f"Parsed {len(current):,} "
    f"Retiring Soon minifigs."
)


# ---------------------------------------------------------
# Report schedule
# ---------------------------------------------------------

now = datetime.now().astimezone(BRUSSELS)

print(
    "Current Brussels time:",
    now.strftime("%Y-%m-%d %H:%M:%S %Z")
)

if now.hour not in TARGET_HOURS:
    print("Silent run: no Discord report is due.")
    raise SystemExit(0)


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
# First successful scan
# ---------------------------------------------------------

if not previous_items:

    STATE_FILE.write_text(
        json.dumps(
            {
                "source": URL,
                "items": current,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


    print(
        "First successful scan."
    )

    print(
        "Baseline saved."
    )

    print(
        "No Discord message sent."
    )

    raise SystemExit(0)


# ---------------------------------------------------------
# Detect added / removed
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
# Detect price changes
# ---------------------------------------------------------

price_changes = []


for code in (
    current_codes & previous_codes
):

    old_price = previous_items[
        code
    ].get("price")

    new_price = current[
        code
    ]["price"]


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


# Largest rises.
gainers = sorted(
    [
        x
        for x in price_changes
        if x[0] >= THRESHOLD
    ],
    reverse=True,
)[:15]


# Largest falls.
losers = sorted(
    [
        x
        for x in price_changes
        if x[0] <= -THRESHOLD
    ]
)[:15]


# ---------------------------------------------------------
# Save state helper
# ---------------------------------------------------------

def save_state():

    STATE_FILE.write_text(
        json.dumps(
            {
                "source": URL,
                "items": current,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------
# No changes = no Discord
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
# Discord message
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
# Send Discord
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
# Save state
# ---------------------------------------------------------

save_state()


print(
    f"Scan complete | "
    f"minifigs: {len(current)} | "
    f"added: {len(added)} | "
    f"removed: {len(removed)} | "
    f"price changes: {len(price_changes)}"
)
