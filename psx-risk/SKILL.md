---
name: psx-risk
description: PSX Risk Manager. The gate between a sized order and the broker app: checks every order in the desk's orders file against the user's limits and prints PASS or BLOCK with the reason. For an entry: a stop is required, the loss at the stop after charges must fit the max loss per trade, reward-to-risk after charges must meet the minimum, today's losses plus open risk must fit the daily loss limit, no more than the day's trade count, no day-trade entry when the market is shut or near the close, position size, cash (PSX settles T+1), holdings cap, PSX price limits and 1-paisa price steps, and no short selling. Exits are never blocked by day limits. Also the risk quiz, position sizing and portfolio risk. Use when the user says "check my order", "is this safe", "risk check", "can I take this trade", "how much have I risked today", and always before psx-broker.
---

# psx-risk

A BLOCK is final for that exact order. These limits keep each loss and each day's losses small;
they don't make a trade win.

`${CLAUDE_SKILL_DIR}` is this skill's folder (where this SKILL.md is); in the Claude app, run the
commands from that folder. Data lives in the user's data folder (`~/pkmarket`, or `PKM_HOME`;
on Android `/storage/emulated/0/pkmarket`), shared with the psx-mufap skill and the other desk
skills: prices, the portfolio ledger, and the desk files in `trader/`.

```bash
python3 scripts/risk.py check                    # trader/orders.json -> trader/risk.json
python3 scripts/risk.py check --live             # measured against live prices
python3 scripts/risk.py check --now "2026-10-26 15:10"   # pin the clock (Pakistan time)
python3 scripts/risk.py quiz                     # the user's risk style (sets every limit)
python3 scripts/risk.py settings                 # every limit, and where it came from
python3 scripts/risk.py set max_trades_per_day 2 # change one
python3 scripts/risk.py portfolio                # money at risk now, value-at-risk, concentration
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the bracket from psx-budget (or psx-broker's flatten) |
| `config.json` + risk style | the limits (`risk.py settings`) |
| portfolio ledger | capital, cash, holdings, today's realised losses |
| `trader/tickets.json` | entries already filled today |
| `trader/risk.json` | verdicts with a fingerprint of each exact order |

## The checks

Entries: stop attached; loss at the stop (from the higher of the order price and a fresh price,
with charges both ways) within `risk_per_trade` x capital; reward-to-risk after charges at least
`min_reward_risk`; today's losses + open risk + this within `daily_loss_limit_pct`; fewer than
`max_trades_per_day` day-trade entries; for a day trade, the market open and not within
`entry_cutoff_min` of the close; size within `max_position_pct`; cost within recorded cash; under
`max_holdings`. Every order: valid side, type (market / limit / stop-loss), whole shares, 1-paisa
price steps, inside today's price limits, no selling shares not held. Exits only fail on format,
short selling or price limits; a target outside today's band is a warning.

## Steps

1. Run `check`; give each verdict and reason in plain words.
2. A BLOCK goes back to psx-exit / psx-budget, never to the user as "place it anyway".
3. All PASS: psx-broker shows the tickets.

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
