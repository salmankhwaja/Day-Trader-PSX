---
name: psx-budget
description: PSX Budget Manager. Sizes a Pakistan Stock Exchange trade to the user's capital and maximum loss per trade, counting broker charges both ways (commission, sales tax, CDC, levies, from the user's broker preset such as AKD or Finqalab), capped by the position limit and recorded cash, in whole shares; writes the bracket the way PSX apps take it: a limit buy, a stop-loss sell (trigger and limit) and an optional take-profit. Use when the user asks "how many shares", "size this trade", "I have 5 lakh and can lose 5,000", "what's my position size", "build the order", or after psx-exit / psx-timemachine.
---

# psx-budget

`${CLAUDE_SKILL_DIR}` is this skill's folder (where this SKILL.md is); in the Claude app, run the
commands from that folder. Data lives in the user's data folder (`~/pkmarket`, or `PKM_HOME`;
on Android `/storage/emulated/0/pkmarket`), shared with the psx-mufap skill and the other desk
skills: prices, the portfolio ledger, and the desk files in `trader/`.

```bash
python3 scripts/budget.py                                   # size the plan on file
python3 scripts/budget.py --write                           # and write trader/orders.json
python3 scripts/budget.py --account 500000 --max-loss 2500 --write   # the user's own numbers
python3 scripts/portfolio.py broker add Finqalab --preset finqalab   # charges come from the broker
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | entry, stop, target (psx-exit) |
| portfolio ledger | capital, cash and the default broker's charges |
| `trader/orders.json` | the bracket: E1 buy, E1-SL stop-loss, E1-TP take-profit |

## The size

The smallest of: max loss (`risk_per_trade` x capital, or `--max-loss`) / the loss per share at the
stop with charges both ways; `max_position_pct` x capital / entry; cash beyond `cash_reserve_pct`.
Whole shares (`lot_size`). The stop-loss order's limit sits `stop_limit_gap` below its trigger, so
it still fills in a fast fall (the loss shown is at the trigger: a fill lower costs more).

## Steps

1. Ask for the capital and the max loss if nothing is recorded.
2. Show the shares, the cost with charges, the loss at the stop and the gain at the target in rupees,
   and which limit decided the size.
3. `--write`, then psx-risk.

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
