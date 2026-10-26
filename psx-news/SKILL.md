---
name: psx-news
description: PSX News Monitor. Reads what each share the user follows has announced to the Pakistan Stock Exchange (financial results, dividends and book closures, board meetings, AGMs, material information, deals, directors' and sponsors' dealings) from each company's PSX page, tags every notice, links its PDF, flags what matters for a short-term trade (a board meeting coming, a book closure, results) and shows today's move when live prices are on file. Use when the user asks "any news on OGDC", "what did LUCK announce", "results this week", "board meetings", "book closures", "why is it moving", or before taking a trade from psx-scanner.
---

# psx-news

`${CLAUDE_SKILL_DIR}` is this skill's folder (where this SKILL.md is); in the Claude app, run the
commands from that folder. Data lives in the user's data folder (`~/pkmarket`, or `PKM_HOME`;
on Android `/storage/emulated/0/pkmarket`), shared with the psx-mufap skill and the other desk
skills: prices, the portfolio ledger, and the desk files in `trader/`.

```bash
python3 scripts/news.py                       # last 3 days: watchlist + holdings (one page per share)
python3 scripts/news.py --days 14 OGDC MARI   # any shares, any window
python3 scripts/news.py --setups --live       # the scanner's names, with today's move
python3 scripts/news.py --cached              # no downloads
python3 scripts/news.py OGDC --from-file page.html   # a company page saved by hand
```

## What it reads and writes

| file | what |
| --- | --- |
| `companies/<SYMBOL>.json` | each company page, refreshed (announcements, payouts, financials) |
| `live.json` | today's prices, if fetched (`--live`, or pkdata.py live) |
| `trader/news.json` | the notices found, what's coming up, today's moves |

## Tags

results, payout, board, meeting, insider, deal, material, other. The "coming up" list warns about
board meetings (results or a payout can land while a trade is open) and book closures (the price
usually drops by about the dividend on the ex-date; buy before it to receive the dividend).

## Steps

1. Run it on the shares in question (or `--setups` after the scanner).
2. Lead with what could move the price: results, payouts, material information, deals.
3. Always give the PDF link and say a title is only a summary: the PDF is the notice.
4. For a day trade, say plainly if a board meeting or results fall today.

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
