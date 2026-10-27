---
name: psx-alerts
description: PSX Price Alerts. Rings when a Pakistan Stock Exchange share hits a price, a stop, a target or a percentage move, or when the clock reaches the opening bell, the flat-by time or any time set; each alert rings once. One live market-watch request covers every share, so many alerts cost the same as one; rings print with a bell and go to phone or desktop notifications (Termux or notify-send) when available. Use when the user says "alert me if OGDC hits 310", "tell me when my stop is hit", "remind me to close by 3:20", "watch my holdings", "ring at the open", or after psx-broker records an entry.
---

# psx-alerts

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
python3 scripts/alerts.py add OGDC --above 310
python3 scripts/alerts.py add OGDC --below 290 --note "support"
python3 scripts/alerts.py add OGDC --move 4                  # 4% either way from yesterday's close
python3 scripts/alerts.py add --at 15:20 --note "flat by"    # a clock alert, Pakistan time
python3 scripts/alerts.py add --from-plan                    # the plan's stop, target and flat-by
python3 scripts/alerts.py add --from-holdings                # every holding's stop
python3 scripts/alerts.py add --bells                        # the open, and 10 minutes before the close
python3 scripts/alerts.py list | remove 3 | clear --fired
python3 scripts/alerts.py check                              # once; rings what hit
python3 scripts/alerts.py watch --every 60                   # while the market is open
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/alerts.json` | the alerts and when each rang |
| `trader/plan.json` | for `--from-plan` |
| `live.json` | the live prices each check fetched |

## Rules

- Each alert rings once (`clear --fired` tidies up). Clock alerts are for today unless `--daily`.
- Prices come from the PSX portal's market watch, which can lag the exchange a little.
- On a phone (Termux), rings arrive as notifications; on a schedule, `alerts.py check` from cron
  every few minutes during market hours works without a terminal open.

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
