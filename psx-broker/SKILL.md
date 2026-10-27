---
name: psx-broker
description: PSX Order Tickets. Turns orders that passed psx-risk into tickets the user types into their own broker app (Finqalab, AKD, KTrade and others: PSX retail apps have no public order API, and nothing here sends orders), shows only READY tickets whose exact order passed the risk check, notes how long the app keeps a stop-loss (Finqalab: today only), records the fill into the user's portfolio ledger once the user says it filled, and writes the sell tickets to get flat before the close. Also lists every holding's stop-loss and take-profit tickets. Use when the user says "give me the tickets", "how do I put this in Finqalab", "it filled at 203.7", "record the buy", "flatten", "close my day trades", or after psx-risk passes.
---

# psx-broker

It never sends an order and never asks for a broker password. The user types every ticket.

`${CLAUDE_SKILL_DIR}` is this skill's folder (where this SKILL.md is); in the Claude app, run the
commands from that folder. Data lives in the user's data folder (`~/pkmarket`, or `PKM_HOME`;
on Android `/storage/emulated/0/pkmarket`), shared with the psx-mufap skill and the other desk
skills: prices, the portfolio ledger, and the desk files in `trader/`.

**In a chat sandbox** (Claude app, Gemini, ChatGPT), the data folder starts empty in each chat: if
it is (`python3 scripts/pkdata.py status`), ask for the user's backup zip and
`python3 scripts/pkdata.py restore FILE.zip`; after recording anything, `python3 scripts/pkdata.py
backup` and send the zip back. PSX prices can't be fetched from most sandboxes: use the backup's
and say their date.


```bash
python3 scripts/broker.py show                         # tickets: READY (passed psx-risk) or not
python3 scripts/broker.py filled E1 --price 203.70     # the user says it filled: into the ledger
python3 scripts/broker.py filled E1 --price 203.70 --qty 500 --time 10:41 --commission 76.40
python3 scripts/broker.py today                        # today's fills, what's still open
python3 scripts/broker.py flatten                      # day trades still open: the SELL tickets
python3 scripts/portfolio.py orders --live             # tickets for every holding (stops, take-profits)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json`, `trader/risk.json` | the orders and their verdicts (fingerprints must match) |
| `trader/tickets.json` | tickets shown, fills confirmed |
| portfolio ledger | the fill, as a trade with date, time, broker, charges and the stop |

## Steps: the entry

1. `show`. Only READY tickets go to the user. A changed or blocked order goes back to psx-risk.
2. Read each READY ticket in plain words: side, shares, symbol, order type, prices, how long it lasts.
3. The user places it in their app. When they say it filled, confirm the price and quantity, then
   `filled` (actual charges from the contract note if they have them).
4. Remind them to place the stop-loss ticket now; for brokers whose stop-loss lasts one day
   (Finqalab), again each morning while they hold.

## Steps: while it's open, and out by the close

- psx-alerts rings at the stop, the target and the flat-by time.
- Near the close: `flatten`, cancel the open stop and take-profit in the app first, then record the exit.

## The desk

The eleven psx-* skills pass work along in `trader/` (one trade, in order):

```
psx-scanner -> psx-news -> psx-entry -> psx-exit -> psx-timemachine -> psx-budget -> psx-risk -> psx-broker
psx-alerts: the stop, the target and the flat-by time while it's open
psx-analyst, psx-insiders: results and insiders' dealings, any time
```
Adapted for PSX from Jake Schincariol's day-trader-skill (MIT).

## Safety

Not financial advice. Rule-based, from public PSX data. Most people who day trade lose money:
say so plainly when the user is about to day trade. Nothing in these skills can place an order:
PSX retail apps (Finqalab, AKD, KTrade and the rest) have no public order API, and the tools would
not use one. The user decides, types the ticket into their own app, and says "yes" for every
trade; never imply otherwise, and never ask for broker passwords. PSX data is for personal use:
don't publish it.
