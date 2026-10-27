---
name: psx-exit
description: PSX Exit Planner. Sets the stop, the target and (for a day trade) the flat-by time before the user enters a Pakistan Stock Exchange trade: stops from the opening range, the scanner's stop idea, the share's volatility or a percentage; targets as a multiple of the risk; checks today's price limits (a target beyond the 10% band can't fill today) and reward-to-risk after broker charges. Writes the plan the other desk skills use. Use when the user asks "where should my stop be", "what's my target", "plan this trade", "when do I get out", "how much am I risking per share", or after psx-entry triggers.
---

# psx-exit

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
python3 scripts/exitplan.py plan SYN07 --write                     # from today's setup: its trigger and stop
python3 scripts/exitplan.py plan OGDC --entry 301.5 --stop or-mid --target 2R --style day --write
python3 scripts/exitplan.py plan OGDC --stop vol --target 2.5R --style swing --days 10 --write
python3 scripts/exitplan.py show
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/setups.json` | the setup, its trigger, stop idea and opening range |
| `live.json`, `psx/<SYMBOL>.csv` | the price when no entry is given |
| `trader/plan.json` | the plan: entry, stop, target, flat-by, reward-to-risk before and after charges |

## Stops and targets

Stops: `or-mid`, `or-low` (opening range), `setup`, `vol` (`stop_atr_mult` x the average daily
move, between `min_stop_pct` and `max_stop_pct`), `5%`, or a price. Targets: `2R` (entry + 2 x the
risk; default `min_reward_risk` for a day trade, `target_r` for a swing) or a price. A day trade is
out `flat_by_min` before the close (15:20 Mon-Thu, 16:20 Friday by default).

PSX specifics it checks: today's price limits (10%, or Rs 1, from yesterday's close; set
`circuit_limit_pct` if PSX changes it): a target above the band can't fill today, a stop below it
can't protect a locked limit-down day. Charges are real money on PSX (commission, sales tax, CDC,
levies, both ways): a tight day trade can look 1.5 to 1 and be under 1 to 1 after charges.

## Steps

1. Make the plan, show it in plain words, with every note.
2. If reward-to-risk after charges is under `min_reward_risk`, say psx-risk will block it.
3. `--write` saves it for psx-timemachine, psx-budget, psx-risk and psx-alerts.

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
