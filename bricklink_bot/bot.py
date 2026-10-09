"""
No-API BrickLink Price Guide Discord bot prototype.

Reads the public BrickLink classic Price Guide page only. It does not use
BrickLink API credentials and deliberately does not bypass CAPTCHA/WAF checks.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import discord
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bricklink-price-bot")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
BRICKLINK_TIMEOUT = int(os.getenv("BRICKLINK_TIMEOUT", "20"))
BRICKLINK_BASE = "https://www.bricklink.com/catalogPG.asp"
USER_AGENT = "Mozilla/5.0 (compatible; BrickLinkPriceGuideHelper/0.1; +https://www.bricklink.com/help.asp?helpID=31)"


class PriceGuideUnavailable(Exception):
    """Public Price Guide page was blocked or its structure was not understood."""


@dataclass
class PriceStats:
    minimum: str | None = None
    average: str | None = None
    maximum: str | None = None
    count: str | None = None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def item_url(item_type: str, item_no: str) -> str:
    # Classic BrickLink Price Guide URL conventions: M=minifig, S=set.
    key = {"MINIFIG": "M", "SET": "S"}[item_type]
    params = {key: item_no, "v": "P", "prDec": "2"}
    return f"{BRICKLINK_BASE}?{urlencode(params)}"


def fetch_price_guide(item_type: str, item_no: str) -> tuple[str, str]:
    url = item_url(item_type, item_no)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=BRICKLINK_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PriceGuideUnavailable(f"Network request failed: {exc}") from exc

    if response.status_code in (401, 403, 429):
        raise PriceGuideUnavailable(
            f"BrickLink returned HTTP {response.status_code}; automated access may be restricted."
        )
    if response.status_code >= 400:
        raise PriceGuideUnavailable(f"BrickLink returned HTTP {response.status_code}.")

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = normalize_text(soup.get_text(" ", strip=True))
    if (
        "verify that you're not a robot" in page_text
        or "enable javascript and then reload" in page_text
        or "aws-waf" in response.text.lower()
    ):
        raise PriceGuideUnavailable(
            "BrickLink showed its anti-bot verification page. This bot will not bypass it. "
            "The public page needs to be accessible normally for this method to work."
        )

    title = soup.title.get_text(" ", strip=True) if soup.title else f"{item_type} {item_no}"
    if len(page_text) < 300:
        raise PriceGuideUnavailable("BrickLink returned too little page content to read safely.")
    return title, response.text


def extract_stats(html: str, section_keywords: tuple[str, ...]) -> PriceStats:
    """
    Best-effort parser for labels in BrickLink's classic Price Guide.
    If BrickLink changes the page markup, return partial data rather than inventing values.
    """
    soup = BeautifulSoup(html, "html.parser")
    stats = PriceStats()
    rows: list[tuple[str, str]] = []

    for row in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip()
                 for c in row.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            rows.append((normalize_text(" ".join(cells[:-1])), cells[-1]))

    full_text = normalize_text(soup.get_text(" ", strip=True))
    for label, value in rows:
        label = label.lower()
        if stats.minimum is None and any(k in label for k in ("lowest price", "min price", "minimum price")):
            stats.minimum = value
        elif stats.average is None and any(k in label for k in ("average price", "avg price")) and "qty" not in label:
            stats.average = value
        elif stats.maximum is None and any(k in label for k in ("highest price", "max price", "maximum price")):
            stats.maximum = value
        elif stats.count is None and any(k in label for k in ("times sold", "number sold", "items sold", "lots")):
            stats.count = value

    # Some versions put the guide summary in text rather than a simple table.
    if not any((stats.minimum, stats.average, stats.maximum, stats.count)):
        if any(k in full_text for k in section_keywords):
            return stats
    return stats


def money(value: str | None) -> str:
    if not value:
        return "niet gevonden"
    value = value.strip()
    # Price Guide page may use another currency according to account/browser settings.
    return value


def format_report(item_type: str, item_no: str, title: str, html: str) -> str:
    # The page's actual current markup differs by item and user session. Until parsing
    # is verified against real pages, don't present guessed numbers as actual prices.
    sold = extract_stats(html, ("past 6 months sales", "last 6 months sales"))
    stock = extract_stats(html, ("current items for sale", "items for sale"))

    if not any((sold.minimum, sold.average, sold.maximum, sold.count,
                stock.minimum, stock.average, stock.maximum, stock.count)):
        raise PriceGuideUnavailable(
            "De openbare pagina laadt, maar ik herken de prijsstatistieken niet betrouwbaar. "
            "Ik geef geen geschatte cijfers door. We moeten de echte BrickLink-paginamarkup "
            "eenmalig controleren voordat ik dit veilig kan afwerken."
        )

    label = "Minifiguur" if item_type == "MINIFIG" else "LEGO-set"
    return (
        f"**BrickLink-prijsgids — {label} {item_no}**\n"
        f"{title}\n"
        f"Bron: {item_url(item_type, item_no)}\n\n"
        "**Verkocht in de afgelopen 6 maanden**\n"
        f"• Minimum: € {money(sold.minimum)}\n"
        f"• Gemiddelde: € {money(sold.average)}\n"
        f"• Maximum: € {money(sold.maximum)}\n"
        f"• Aantal verkopen: {money(sold.count)}\n\n"
        "**Momenteel te koop**\n"
        f"• Minimum vraagprijs: € {money(stock.minimum)}\n"
        f"• Gemiddelde vraagprijs: € {money(stock.average)}\n"
        f"• Maximum vraagprijs: € {money(stock.maximum)}\n"
        f"• Aantal aanbiedingen: {money(stock.count)}\n\n"
        "_Controleer de valuta op BrickLink; de openbare pagina kan de ingestelde accountvaluta gebruiken._"
    )


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    log.info("BrickLink price bot is online as %s", client.user)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    raw = message.content.strip()
    if not raw.startswith("!"):
        return

    # !price twn486, !price 10326, or the shortcut !10326
    parts = raw[1:].split()
    if not parts:
        return

    if parts[0].lower() == "price":
        if len(parts) != 2:
            await message.reply("Gebruik: `!price twn486` voor een minifiguur.")
            return
        item_no = parts[1].strip()
    else:
        if len(parts) != 1 or not re.fullmatch(r"[0-9][0-9-]*", parts[0]):
            return
        item_no = parts[0].strip()

    if re.fullmatch(r"[0-9][0-9-]*", item_no):
        item_type = "SET"
        if "-" not in item_no:
            item_no = f"{item_no}-1"
    elif re.fullmatch(r"[A-Za-z]{2,}[A-Za-z0-9_-]*", item_no):
        item_type = "MINIFIG"
    else:
        await message.reply("Ik herken dat itemnummer niet. Voorbeelden: `!price twn486` of `!10326`.")
        return

    async with message.channel.typing():
        try:
            title, html = await __import__("asyncio").to_thread(fetch_price_guide, item_type, item_no)
            report = format_report(item_type, item_no, title, html)
            await message.reply(report, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except PriceGuideUnavailable as exc:
            await message.reply(
                "⚠️ Ik kon de BrickLink-prijsgegevens niet veilig uitlezen.\n"
                f"{exc}\n\n"
                f"Je kunt de prijswijzer zelf openen: {item_url(item_type, item_no)}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            log.exception("Unexpected error while processing %s", item_no)
            await message.reply("Er ging iets mis bij het verwerken van dit item. De fout is gelogd.")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("Missing DISCORD_BOT_TOKEN environment variable.")
    client.run(DISCORD_BOT_TOKEN)
