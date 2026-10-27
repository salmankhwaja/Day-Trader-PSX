---
name: psx-analyst
description: PSX Earnings Analyst. Reads a Pakistan Stock Exchange company's latest results from its PSX page (annual and quarterly sales, profit after tax and EPS, margins and EPS growth, data by Capital Stake) and sums up what changed: the latest quarter against the same quarter last year and the quarter before, the latest year against the year before, net margin, P/E on the latest annual EPS, dividends over 12 months and the payout ratio, with the results notice and its PDF. Compares several companies side by side. Use when the user asks "how were OGDC's results", "did profits grow", "EPS", "compare MARI and PPL", "is it cheap", "what changed this quarter".
---

# psx-analyst

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
python3 scripts/analyst.py OGDC                  # refreshes the company page, then the summary
python3 scripts/analyst.py OGDC MARI PPL         # side by side
python3 scripts/analyst.py OGDC --cached         # what's on file
python3 scripts/analyst.py OGDC --from-file page.html
```

## What it reads and writes

| file | what |
| --- | --- |
| `companies/<SYMBOL>.json` | the company page: financials, ratios, payouts, announcements |
| `trader/financials/<SYMBOL>.json` | the summary |

## The rules

- Figures are in thousands of rupees (EPS in rupees), as the portal shows them; the portal credits
  Capital Stake and says they may be standardised. For "as reported" numbers, open the results PDF.
- Pakistani companies' fiscal years differ (many end in June): name the period, not just the year.
- Summarise what changed in words first, then the numbers. Don't call a share cheap or dear: give
  the P/E and growth and let the user judge.

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
