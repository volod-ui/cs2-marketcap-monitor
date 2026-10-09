# BrickLink Discord price bot — no-API feasibility prototype

This branch isolates an experimental Discord bot from the existing crypto and BrickEconomy workflows.

## Commands planned

- \`!price twn486\` — look up a minifigure by exact catalog ID
- \`!10326\` — look up LEGO set 10326 (mapped to BrickLink ID \`10326-1\`)

The intended report is used-item sales over the previous six months plus current used listings, including minimum, maximum, average and counts.

## Important feasibility result

**This is not ready to deploy.** BrickLink documents the Price Guide as two live sections: past six months sales and current items for sale. See the official [Price Guide help](https://www.bricklink.com/help.asp?helpID=31).

The public classic Price Guide can return a JavaScript anti-bot/WAF challenge to automated HTTP requests. The prototype intentionally does not attempt to defeat that challenge. BrickLink's API terms also point automated robots/spiders to a separate policy and prohibit reverse-engineering internal data feeds or accessing legacy/internal APIs that are not public API resources. We will not use those routes as a workaround.

Consequently, **the no-API method is not yet proven to provide the historical sold data reliably**. The bot currently fails closed if it cannot identify the two sections and currency independently. It must not be hosted or treated as a working price source until a normal, permitted response has been tested against both a set and a minifigure.

If the no-API route cannot provide both sections reliably, the legitimate options are:
1. Use the official API if eligible and authorized.
2. Use the public Price Guide manually for the sold-history part, while separately evaluating a permitted source for current listings.
3. Ask BrickLink whether they offer an authorized access route for this use case.

## Local test

Use Python 3.11+:

\`\`\`bash
cd bricklink_bot
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
\`\`\`

Set \`DISCORD_BOT_TOKEN\` as an environment variable and run:

\`\`\`bash
python bot.py
\`\`\`

In the Discord Developer Portal, enable **Message Content Intent**. Invite the bot with permission to view the intended channel, read message history and send messages. Keep the token secret; never commit it to GitHub.

## Before hosting

- Verify the page can be accessed by ordinary, permitted requests from the intended environment.
- Validate the parser against real HTML for one set and one minifigure.
- Confirm sold and stock metrics are separate, and the displayed currency is explicit.
- Add name search/disambiguation only after exact-ID lookups work.
- Add hosting and restart policy only after the data checks pass.

No changes are made to the existing crypto or BrickEconomy bot workflows.
