---
name: psx-insiders
description: PSX Insider Tracker. Finds when directors, the CEO, executives, sponsors and substantial shareholders of Pakistan Stock Exchange companies buy or sell their own company's shares, from the disclosure notices companies post on their PSX pages ("Transaction in shares by Director", "Disclosure of interest", "Purchase of shares by Sponsor"), with buy/sell where the title says and the PDF that names who, how many and at what price; can show only what's new since the last run. The PSX cousin of a Pelosi tracker. Use when the user asks "are insiders buying", "director dealings", "did the sponsor sell", "insider trades in LUCK", "who's buying their own stock".
---

# psx-insiders

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
python3 scripts/insiders.py                       # last 30 days: watchlist + holdings
python3 scripts/insiders.py --days 90 OGDC LUCK
python3 scripts/insiders.py --all                 # every listed share: ~10 minutes, one page a second
python3 scripts/insiders.py --new                 # only what's new since the last run (for a schedule)
python3 scripts/insiders.py --cached
```

## What it reads and writes

| file | what |
| --- | --- |
| `companies/<SYMBOL>.json` | each company page's announcements (refreshed unless `--cached`) |
| `trader/insiders.json` | the notices found, and what has been shown (for `--new`) |

## The rules

- A notice is an insider dealing when its title names an insider (director, CEO, CFO, executive,
  sponsor, substantial or beneficial owner) and a dealing (transaction, purchase, sale, acquisition,
  disposal, disclosure of interest). "Election of directors" isn't one.
- Buy or sell is read from the title when it says; otherwise "?" and the PDF has it.
- Public filings, for information. An insider sells for many reasons and buys for a few: never
  present one notice as a signal. Name the person only as the PDF does.

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
