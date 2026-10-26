---
name: psx-scanner
description: PSX Chart Scanner. Finds today's trade setups on the Pakistan Stock Exchange: before the open, daily setups in the end-of-day charts (breakouts above a 20-day high on volume, bull flags, oversold bounces, 52-week highs, gaps, volume surges) across the watchlist or every liquid listed share; during the session, opening-range breakouts from the PSX portal's intraday trades; and right now, the biggest gainers, losers and most-traded shares from one live request. Each setup comes with a trigger and a stop idea, and today's price limits. Use when the user asks "what's setting up", "scan PSX", "any breakouts today", "top gainers", "opening range breakout", "what should I watch today", or to start a trade.
---

# psx-scanner

Finds candidates. It never says buy: it says what fired and why, with the price that would confirm
it and the price that would prove it wrong.

`${CLAUDE_SKILL_DIR}` is this skill's folder (where this SKILL.md is); in the Claude app, run the
commands from that folder. Data lives in the user's data folder (`~/pkmarket`, or `PKM_HOME`;
on Android `/storage/emulated/0/pkmarket`), shared with the psx-mufap skill and the other desk
skills: prices, the portfolio ledger, and the desk files in `trader/`.

```bash
python3 scripts/scanner.py daily --no-fetch            # before the open: watchlist + holdings
python3 scripts/scanner.py daily --all --fetch          # every liquid share (after pkdata.py universe; slow first time)
python3 scripts/scanner.py orb                          # during the session: opening-range breakouts
python3 scripts/scanner.py orb --at 10:30               # as of a time; replays: --now "2026-10-26 10:30"
python3 scripts/scanner.py movers                       # gainers, losers, most traded, right now
python3 scripts/watchlist.py add LUCK DGKC --fetch      # change what it scans
```

## What it reads and writes

| file | what |
| --- | --- |
| `psx/<SYMBOL>.csv` | end-of-day prices (pkdata.py psx) |
| `intraday/<date>/<SYMBOL>.json` | today's trades (fetched by `orb`, kept for the time machine) |
| `trader/setups.json` | what it found, for psx-entry, psx-exit and psx-news |

## The setups

| setup | fires when | trigger | stop idea |
| --- | --- | --- | --- |
| breakout | closes above its highest close of the previous 20 sessions, on 1.5x volume | that close | the old high less one average daily move |
| flag | up 8%+ in ten sessions, then five sessions in a band under 4% wide | top of the band | bottom of the band |
| bounce | RSI(14) under 30 yesterday, higher close today | today's close | lowest close of the week |
| high52 | within 2% of its 52-week high close | the high | two average moves below |
| gap | opens 3%+ above the previous close | the open | the previous close |
| surge | 3x average volume and up 2%+ | the close | the previous close |
| orb | a 5-minute close above the high of the first `orb_minutes` (09:32 Mon-Thu, 09:17 Fri) | range high | range middle |

With `--all`, shares trading less than `scan_min_value_traded` rupees a day are left out. PSX's
free daily series has closes but no daily highs and lows, so daily setups use closes.

## Steps

1. Ask which prices to use (last fetch / fresh / live). **Before any advice, ask which prices to use** (the same rule as psx-mufap): the last fetch
(`--no-fetch`), a fresh end-of-day fetch (`--fetch`), or live prices (`--live`, during market
hours). State the date or time of the data in your answer.
2. Before 09:15: `daily`. After the range (about 09:47 Mon-Thu): `orb`, which reads the daily
   shortlist (or the watchlist) and asks PSX for each share's trades, one a second, so keep it short.
3. Show the table and the "why" for each. Flag any share at today's upper price limit (`movers`
   notes it): few sellers there, so buying is hard.
4. Offer the next step: psx-news on the names the user likes, then psx-entry.

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
