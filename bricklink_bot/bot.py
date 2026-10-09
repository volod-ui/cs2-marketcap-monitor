"""
No-API BrickLink Price Guide Discord bot.
Only reads the public Price Guide and does not bypass CAPTCHA/WAF checks.
It fails closed unless sold and stock sections can be identified independently.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlencode
import discord
import requests
from bs4 import BeautifulSoup, Tag

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bricklink-price-bot")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
BRICKLINK_TIMEOUT = int(os.getenv("BRICKLINK_TIMEOUT", "20"))
BRICKLINK_BASE = "https://www.bricklink.com/catalogPG.asp"
USER_AGENT = "Mozilla/5.0 (compatible; BrickLinkPriceGuideHelper/0.2; +https://www.bricklink.com/help.asp?helpID=31)"

class PriceGuideUnavailable(Exception):
    """Price Guide could not be read reliably."""

@dataclass
class PriceStats:
    minimum: str | None = None
    average: str | None = None
    maximum: str | None = None
    count: str | None = None
    def complete(self) -> bool:
        return all((self.minimum, self.average, self.maximum, self.count))

def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()

def item_url(item_type: str, item_no: str) -> str:
    key = {"MINIFIG": "M", "SET": "S"}[item_type]
    return f"{BRICKLINK_BASE}?{urlencode({key: item_no, 'v': 'P', 'prDec': '2'})}"

def fetch_price_guide(item_type: str, item_no: str) -> tuple[str, str]:
    url = item_url(item_type, item_no)
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}, timeout=BRICKLINK_TIMEOUT)
    except requests.RequestException as exc:
        raise PriceGuideUnavailable("De verbinding met BrickLink is mislukt.") from exc
    if response.status_code in (401, 403, 429):
        raise PriceGuideUnavailable(f"BrickLink gaf HTTP {response.status_code}; geautomatiseerde toegang kan beperkt zijn.")
    if response.status_code >= 400:
        raise PriceGuideUnavailable(f"BrickLink gaf HTTP {response.status_code}.")
    soup = BeautifulSoup(response.text, "html.parser")
    text = normalize_text(soup.get_text(" ", strip=True))
    if "verify that you're not a robot" in text or "enable javascript and then reload" in text or "aws-waf" in response.text.lower():
        raise PriceGuideUnavailable("BrickLink toont een anti-botcontrole. Ik probeer die niet te omzeilen.")
    if len(text) < 300:
        raise PriceGuideUnavailable("BrickLink gaf te weinig leesbare pagina-inhoud terug.")
    title = soup.title.get_text(" ", strip=True) if soup.title else f"{item_type} {item_no}"
    return title, response.text

def find_section(soup: BeautifulSoup, keywords: tuple[str, ...]) -> Tag | None:
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "th", "td", "b", "strong", "font"]):
        label = normalize_text(heading.get_text(" ", strip=True))
        if not label or not any(keyword in label for keyword in keywords):
            continue
        parent = heading
        for _ in range(4):
            if not isinstance(parent.parent, Tag):
                break
            parent = parent.parent
            if parent.name in ("table", "section", "div") and len(normalize_text(parent.get_text(" ", strip=True))) > len(label) + 10:
                return parent
        if isinstance(heading.parent, Tag):
            return heading.parent
    return None

def parse_stats(section: Tag) -> PriceStats:
    stats = PriceStats()
    for row in section.find_all("tr"):
        cells = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip() for cell in row.find_all(["th", "td"])]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2:
            continue
        label, value = normalize_text(" ".join(cells[:-1])), cells[-1]
        if stats.minimum is None and any(x in label for x in ("lowest price", "min price", "minimum price")):
            stats.minimum = value
        elif stats.average is None and any(x in label for x in ("average price", "avg price")) and "qty" not in label:
            stats.average = value
        elif stats.maximum is None and any(x in label for x in ("highest price", "max price", "maximum price")):
            stats.maximum = value
        elif stats.count is None and any(x in label for x in ("times sold", "number sold", "lots", "stores")):
            stats.count = value
    if not stats.complete():
        text = normalize_text(section.get_text(" ", strip=True))
        patterns = {
            "minimum": r"(?:lowest|min(?:imum)? price)\s*[:：]?\s*([$€£]?\s*[0-9][0-9.,]*)",
            "average": r"(?:average|avg) price\s*[:：]?\s*([$€£]?\s*[0-9][0-9.,]*)",
            "maximum": r"(?:highest|max(?:imum)? price)\s*[:：]?\s*([$€£]?\s*[0-9][0-9.,]*)",
            "count": r"(?:times sold|number sold|lots|stores)\s*[:：]?\s*([0-9][0-9,]*)",
        }
        for key, pattern in patterns.items():
            if getattr(stats, key) is None:
                match = re.search(pattern, text)
                if match:
                    setattr(stats, key, match.group(1).strip())
    return stats

def detect_currency(html: str) -> str | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if "€" in text or re.search(r"\bEUR\b", text, re.I):
        return "EUR"
    if "$" in text or re.search(r"\bUSD\b", text, re.I):
        return "USD"
    if "£" in text or re.search(r"\bGBP\b", text, re.I):
        return "GBP"
    return None

def format_report(item_type: str, item_no: str, title: str, html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    sold_section = find_section(soup, ("past 6 months sales", "last 6 months sales"))
    stock_section = find_section(soup, ("current items for sale", "items for sale"))
    if sold_section is None or stock_section is None or sold_section is stock_section:
        raise PriceGuideUnavailable("Ik kan de secties 'verkocht in 6 maanden' en 'momenteel te koop' niet betrouwbaar apart herkennen.")
    sold, stock = parse_stats(sold_section), parse_stats(stock_section)
    if not sold.complete() or not stock.complete():
        raise PriceGuideUnavailable("De pagina is bereikbaar, maar niet alle statistieken zijn betrouwbaar herkend. Ik toon daarom geen mogelijk foutieve cijfers.")
    currency = detect_currency(html)
    if currency is None:
        raise PriceGuideUnavailable("De valuta is niet duidelijk op de pagina. Ik geef geen bedragen met een gegokte valuta weer.")
    label = "Minifiguur" if item_type == "MINIFIG" else "LEGO-set"
    return (
        f"**BrickLink-prijsgids — {label} {item_no}**\n{title}\n<{item_url(item_type, item_no)}>\n\n"
        "**Verkocht in de afgelopen 6 maanden**\n"
        f"• Minimum: {currency} {sold.minimum}\n• Gemiddelde: {currency} {sold.average}\n• Maximum: {currency} {sold.maximum}\n• Aantal verkopen: {sold.count}\n\n"
        "**Momenteel te koop**\n"
        f"• Minimum vraagprijs: {currency} {stock.minimum}\n• Gemiddelde vraagprijs: {currency} {stock.average}\n• Maximum vraagprijs: {currency} {stock.maximum}\n• Aantal aanbiedingen/winkels: {stock.count}\n\n"
        "_Prijsgidswaarden; verzendkosten en eventuele btw kunnen apart gelden._"
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
    parts = raw[1:].split()
    if not parts:
        return
    if parts[0].lower() == "price":
        if len(parts) != 2:
            await message.reply("Gebruik: !price twn486 voor een minifiguur.")
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
        await message.reply("Ik herken dat itemnummer niet. Voorbeelden: !price twn486 of !10326.")
        return
    async with message.channel.typing():
        try:
            title, html = await asyncio.to_thread(fetch_price_guide, item_type, item_no)
            report = format_report(item_type, item_no, title, html)
            await message.reply(report, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except PriceGuideUnavailable as exc:
            await message.reply(
                f"⚠️ Ik kon de BrickLink-prijsgegevens niet veilig uitlezen.\n{exc}\n\nZelf openen: <{item_url(item_type, item_no)}>",
                mention_author=False, allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            log.exception("Unexpected error while processing %s", item_no)
            await message.reply("Er ging iets mis bij het verwerken van dit item. De fout is gelogd.")

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("Missing DISCORD_BOT_TOKEN environment variable.")
    client.run(DISCORD_BOT_TOKEN)
