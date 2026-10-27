---
name: psx-timemachine
description: PSX Time Machine. Before the user risks a rupee, replays a Pakistan Stock Exchange trade plan thousands of times from the share's own past: swing plans string together the share's daily moves in 5-day blocks from its last two years (capped at PSX's daily price limit); day plans string together 5-minute bars from the same time of day on cached intraday sessions. It also replays every past day the same setup fired in that share. Reports target-first, stop-first and still-open odds and the average outcome in R. Use when the user asks "what are the odds", "how often does this work", "replay this trade", "backtest this setup", "is this a good trade", or after psx-exit.
---

# psx-timemachine

A reality check, not a forecast.

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
python3 scripts/timemachine.py run                       # the plan on file, 10,000 replays
python3 scripts/timemachine.py run --sims 20000 --seed 7 --write
python3 scripts/timemachine.py run --symbol OGDC --entry 300 --stop 291 --target 318 --days 10
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | entry, stop, target, style, horizon or flat-by |
| `psx/<SYMBOL>.csv` | five years of daily closes (swing replays and history) |
| `intraday/<date>/<SYMBOL>.json` | cached sessions (day replays need at least 10) |
| `trader/timemachine.json` | the result |

## How it counts

- **Swing**: daily log returns from the last ~500 sessions, drawn in 5-day blocks, each day capped
  at the price limit, for the plan's horizon; first close at or below the stop, or at or above the
  target, decides. Closing prices only (PSX's free daily series has no highs and lows), so real
  stops can trigger intraday a little more often than shown: say so.
- **Day**: 5-minute bars (gap, high, low, close relative to the open) drawn from the same time of
  day on cached sessions, from now to the flat-by time. Each day intraday.py or `scanner.py orb`
  fetches a share, one more session is cached; under 10, it says how many it has.
- **History**: every past day the plan's setup fired in the share (scanner rules), the same
  percentage stop and target applied; for an ORB, every cached session's breakout.
- The seed defaults to today's date, so the same question gives the same answer today.

## Steps

1. Run it on the plan; show simulated and historical odds together, with the verdict.
2. Explain "mostly neither" when the horizon is short for the distances.
3. Never present the odds as a promise; results, policy news or a halt can do what the past didn't.

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
