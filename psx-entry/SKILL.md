---
name: psx-entry
description: PSX Entry Timer. Watches a setup bar by bar and says the moment to get in on the Pakistan Stock Exchange: waiting, triggered or expired. Opening-range breakouts trigger on the first 5-minute close above the range high (from the PSX portal's intraday trades), price levels on a 5-minute close at or above the level; a setup expires when price falls back under the range middle, runs too far to chase, or the day's entry cutoff passes. Use when the user says "tell me when it breaks out", "is it time to buy", "has OGDC triggered", "watch this setup", "wait for the breakout", or after psx-scanner.
---

# psx-entry

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
python3 scripts/entry.py check SYN07                  # the share's setup from today's scanner run
python3 scripts/entry.py check OGDC --setup orb       # opening-range breakout
python3 scripts/entry.py check OGDC --level 305       # a level the user chose
python3 scripts/entry.py watch OGDC --every 60        # keep checking until it triggers or expires
python3 scripts/entry.py check OGDC --now "2026-10-26 10:15"   # replay a moment (cached intraday data)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/setups.json` | the scanner's setup and trigger for the share |
| `intraday/<date>/<SYMBOL>.json` | today's trades, built into 5-minute bars |
| `trader/entry.json` | the last verdict |

## The rule

- **orb**: waiting while the first `orb_minutes` form; triggered by the first 5-minute close above
  the range high; expired if it closes back under the range middle, if it's already more than a
  range-width above the high, or within `entry_cutoff_min` of the close.
- **level**: triggered on a 5-minute close at or above the level; expired 3% above it, or near the close.
- PSX sessions: Monday-Thursday 09:32-15:30; Friday 09:17-12:00 and 14:32-16:30 (a lunch break).

## Steps

1. Check once and report the verdict with its reason and time (Pakistan time).
2. If the user wants to wait, `watch` (it rings when it triggers).
3. Triggered is not an order: next is psx-exit (plan), psx-timemachine, psx-budget, psx-risk.

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
