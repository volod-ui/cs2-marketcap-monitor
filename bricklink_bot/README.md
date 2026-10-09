# BrickLink Discord price bot (no API prototype)

This folder contains an experimental Discord bot that tries to read BrickLink's public classic Price Guide page. It does **not** use BrickLink API keys.

## Current status — prototype, not production-ready

BrickLink's public Price Guide exists at https://www.bricklink.com/catalogPG.asp and documents the six-month sales and current-for-sale sections. However, the page may return a JavaScript anti-bot/WAF challenge to automated requests. This prototype deliberately does not bypass that protection. The page markup and currency behavior also need validation against a real successful response before any values can be trusted.

If the bot reports that it could not read the data, it will link to the relevant BrickLink Price Guide page instead of inventing prices.

## Commands

- `!price twn486` — look up a minifigure number
- `!10326` — look up LEGO set 10326 (mapped to BrickLink set number `10326-1`)

The current prototype supports exact catalog IDs only. Searching names and disambiguating multiple results is not implemented yet.

## Local test

Use Python 3.11+:

```bash
cd bricklink_bot
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variable `DISCORD_BOT_TOKEN` and run:

```bash
python bot.py
```

In the Discord Developer Portal, enable **Message Content Intent** for the application bot. Invite it to your server with permissions to view channels, read message history, and send messages. Keep the token secret.

## Next steps before hosting

1. Verify that the Price Guide page is accessible without an API key from the intended hosting environment.
2. Validate the HTML parser against a real successful response for one set and one minifigure.
3. Confirm EUR currency handling and separate sold-vs-stock summaries.
4. Add hosting and restart policy only after those checks pass.

Do not put Discord tokens or credentials in this repository. Use the hosting provider's secret/environment-variable settings.
