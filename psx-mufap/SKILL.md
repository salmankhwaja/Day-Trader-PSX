---
name: psx-mufap
description: Rank Pakistan Stock Exchange (PSX) stocks (watchlist or every listed share, by sector, Shariah/KMI status and dividend yield) and MUFAP mutual funds, backtest strategies, propose a paper portfolio from backtests, track dividends and book closures, and build a comparison dashboard. Use when the user asks which PSX shares, sectors or Pakistani mutual funds are doing well, about dividends or Shariah compliance of PSX stocks, wants to compare companies, backtest, paper trade or see the dashboard. Never places real orders.
---

# PSX & MUFAP: rank, backtest, paper trade

Plain Python 3.8+, standard library only, in `scripts/`. Every tool prints Markdown
tables that read well on a phone. Run them with `python3 scripts/<tool>.py ...`
from this skill's folder. All data and the paper account live in one folder, the
"home": `~/pkmarket` unless `PKM_HOME` or `--home` says otherwise. `pkdata.py init` creates
it with a starter `config.json`. The home holds the user's data only; never commit it to the
code repository.

| Tool | Job |
|---|---|
| `pkdata.py` | Download or import PSX daily prices and the MUFAP fund table |
| `rank.py` | Rank stocks (returns, risk, trend, vs KSE-100) and funds (within category) |
| `backtest.py` | Test strategies with next-day fills, costs and out-of-sample checks |
| `paper.py` | Pretend PKR account: buy/sell shares, invest/redeem funds, follow signals, credit dividends |
| `propose.py` | Screen, backtest out-of-sample, propose a paper portfolio; review holdings daily |
| `dashboard.py` | Build the visual dashboard (compare, screener, portfolio, dividends, funds) and serve it |
| `daily_sync.sh`, `install_services.sh` | The daily pipeline and its systemd timer, for the user's computer |

## Step 1: get fresh data

First check what is already there: `python3 scripts/pkdata.py status`.

Then try a direct download:

```
python3 scripts/pkdata.py psx --watchlist      # watchlist from config.json + KSE100
python3 scripts/pkdata.py mufap
```

If a download fails (the Claude phone app's sandbox blocks most websites), get the
same page another way, save the body to a file, and import it:

1. **MUFAP:** fetch `https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=1` with
   whatever web tool you have (a web fetch or scrape tool; ask for Markdown or HTML of the
   full page, not a summary). Save it, e.g. `mufap.md`, then
   `python3 scripts/pkdata.py mufap --from-file mufap.md`.
   The parser needs the table rows and the "(Annualized/Absolute Return)" category headings.
2. **PSX:** fetch `https://dps.psx.com.pk/timeseries/eod/<SYMBOL>` and ask for the raw
   JSON body verbatim. Save it and run `pkdata.py psx <SYMBOL> --from-file <file>`.
   A summarised answer is useless here: the tool needs the full `data` array.
3. If PSX can't be reached from this session at all, say so plainly and use the data the
   user syncs from their computer (`scripts/daily_sync.sh`, see README), or rank funds only.

**Whole market, sectors, Shariah, dividends.** The watchlist is the default scope. For every
listed share (about 500), build the universe once, then prices and company pages:

```
python3 scripts/pkdata.py universe          # all listed shares + KMI All Share (Shariah) flags
python3 scripts/pkdata.py company --all     # sector, P/E, 52-week range, full dividend history (7-day cache)
python3 scripts/pkdata.py psx --all         # prices for every share (about 10 minutes, 1 request/second)
python3 scripts/pkdata.py payouts           # latest dividend announcements and book closures
```

The first full run takes 15-20 minutes and is meant for the user's computer (`daily_sync.sh`
with `PKM_SCOPE=all`), not the phone sandbox. On the phone, use the synced data, or a
watchlist (`company --watchlist`, `psx --watchlist`) fetched page by page via `--from-file`.
The fallback pages are `https://dps.psx.com.pk/indices/ALLSHR`, `/indices/KMIALLSHR`,
`/company/<SYMBOL>` and `/payouts`.

Always tell the user the date of the data you used. `pkdata.py status` shows it.

## Step 2: answer "what is doing well?"

```
python3 scripts/rank.py stocks                     # top 10 of the watchlist by score
python3 scripts/rank.py stocks --sort 3m --top 5
python3 scripts/rank.py stocks --all --top 20             # every liquid listed share
python3 scripts/rank.py stocks --all --shariah --sector cement
python3 scripts/rank.py stocks --all --sort div_yield     # highest trailing dividend yield
python3 scripts/rank.py sectors                           # sector league table
python3 scripts/rank.py categories                 # overview of every MUFAP category
python3 scripts/rank.py funds --category "Equity" --top 5
python3 scripts/rank.py funds --category "Money Market" --sort d30
```

How to read and report the results:

- **Stocks score** = average percentile across the list of the 1M, 3M, 6M, 1Y returns and
  the 1Y Sharpe ratio. "3M vs idx" is the stock's 3-month return minus KSE-100's. "Trend" is
  the last close against its 50- and 200-day averages.
- **Funds are ranked only inside their own category.** Money market, income and
  fixed-rate categories quote ANNUALISED returns; equity, balanced, asset-allocation and
  fund-of-funds quote ABSOLUTE returns. Never compare a number from one group with the
  other. The fund score needs at least two of 30D/90D/1Y.
- Distinguish Shariah-compliant categories; they are separate rows in MUFAP.
- Lead with the answer (the top names and why), then the table. Keep it to one screen.
- PSX prices exclude dividends, so high-dividend stocks look weaker than they were.
- ☪ marks KMI All Share members (PSX's Shariah-compliant list, recomposed periodically).
- **Dividend yield** = cash dividends announced in the last 12 months / price, with dividend per
  share = percent x face value. Face value is assumed Rs 10 unless `face_values` in
  config.json says otherwise; say so when quoting yields. A very high yield is often a one-off.
- **Next dividend**: a book closure already announced is fact. "Expected around" is only an
  estimate from last year's announcement date; always label it as an estimate.
- With `--all`, shares averaging under `min_avg_volume` (default 50,000) a day over 60 sessions
  are left out as too illiquid to trade; the output says how many.

## Step 3: backtest

```
python3 scripts/backtest.py compare OGDC                       # all strategies, defaults
python3 scripts/backtest.py run OGDC --strategy sma --fast 50 --slow 200
python3 scripts/backtest.py run LUCK --strategy breakout --optimize
python3 scripts/backtest.py momentum --hold 3 --lookback 126 --rebalance 21
python3 scripts/backtest.py run --fund "NBP Islamic Energy Fund" --strategy sma --fast 10 --slow 30
```

Strategies: `buyhold`, `sma` (moving-average crossover), `breakout` (N-day high in, M-day
low out), `rsi` (buy oversold, sell on recovery), and `momentum` (rotate monthly into the
top-K watchlist stocks by 6-month return, cash when nothing is rising). Details and
parameters: `references/strategies.md`.

Report backtests honestly:
- Always show the strategy next to buy-and-hold over the same days.
- With `--optimize`, the **out-of-sample** row is the result. Say so. If it is far worse than
  in-sample, the tuning found noise.
- Mention costs (`cost_bps_per_side`, default 20 bps) and that cash earns
  `risk_free_annual` (default 0; suggest setting it near a money-market yield, since parking
  cash in a money-market fund is the real alternative in Pakistan).
- Fund backtests only cover NAV days collected by past `pkdata.py mufap` runs; with fewer
  than ~60 days the tool refuses.
- Never present a backtest as a prediction or a recommendation to buy.

## Step 4: propose a portfolio from backtests

```
python3 scripts/propose.py run                    # watchlist
python3 scripts/propose.py run --all --shariah    # whole market, Shariah-compliant only
python3 scripts/propose.py run --all --apply      # after the user says yes
python3 scripts/propose.py review                 # daily: HOLD or SELL each holding
```

`run` takes the top 15 by score, tunes sma/breakout/rsi on 70% of each history, and passes a
stock only if its out-of-sample run beat the cash yield, had a positive Sharpe, kept drawdown
under 35%, and its signal is long today. Picks: up to 5, at most 2 per sector, equal-sized.
Show the table, explain why the picks passed and others failed, and **ask before `--apply`**.
`review` suggests SELL when a holding's strategy turns flat or it falls 15% below cost; again
confirm before `review --apply`.

## Step 5: paper trade

```
python3 scripts/paper.py init --cash 1000000
python3 scripts/paper.py buy OGDC 500                 # at the latest downloaded close
python3 scripts/paper.py invest "Alfalah Cash Fund - II" 200000
python3 scripts/paper.py signals --strategy momentum  # shows proposed orders only
python3 scripts/paper.py status
python3 scripts/paper.py dividends --apply            # credit dividends/bonus shares whose book closure passed
```

Rules:
- **Confirm before booking.** Show the user the orders from `signals` (or the trade they
  asked for) and only run `--apply`, `buy`, `sell`, `invest` or `redeem` after they say yes.
- If a fill price is flagged STALE, refresh the data first or tell the user.
- Nothing here can place a real order. If the user asks to trade for real, say this skill
  only paper trades and they should use their broker.
- The account is `paper/portfolio.json` in the home. Claude's sandbox may not keep files
  between chats: at the end of a session that changed the account, save the file where the
  user keeps it (their own private storage if they have one connected, otherwise send it to them) and tell
  them where it went. At the start of a session, restore it from there before running
  `paper.py`.

## Step 6: the dashboard

```
python3 scripts/dashboard.py build                     # <home>/dashboard/ (index.html, app.js, data.json)
python3 scripts/dashboard.py build --standalone pkm.html   # one self-contained file
python3 scripts/dashboard.py serve                     # http://127.0.0.1:8787
```

Views: Overview (KSE-100, sectors, top ranked, upcoming dividends), Screener (filter by sector,
Shariah, yield; tick up to 6 to compare), Compare (rebased prices, returns, risk, valuation,
dividends side by side), Portfolio (value vs KSE-100, allocation, holdings with review action
and next dividend, latest proposal), Dividends (calendar, top yields), Funds (MUFAP by category).

On the phone: when the user asks to see it, build the standalone file and send it, or publish
it as a **private** artifact only if they ask (it contains PSX data: never share it publicly).
The user's own computer runs it continuously via `install_services.sh`; they reach it over a
private network such as Tailscale.

## Settings

`config.json` in the home (optional; anything missing uses the default):

```json
{
  "watchlist": ["OGDC", "PPL", "MARI", "HUBC", "LUCK", "MCB", "MEBL", "ENGRO", "FFC", "SYS"],
  "benchmark": "KSE100",
  "cost_bps_per_side": 20,
  "lot_size": 1,
  "risk_free_annual": 0.0,
  "paper_starting_cash": 1000000,
  "min_avg_volume": 50000,
  "dividend_tax": 0.15,
  "face_values": {"SYMBOL": 5}
}
```

`dividend_tax` is the withholding rate applied to paper dividends (an assumption: rates differ
for filers and non-filers; ask the user).

`cost_bps_per_side` and `lot_size` are assumptions: ask the user what their broker charges
if it matters. Sources and data caveats: `references/data-sources.md`.

## Boundaries

This is research and education, not investment advice. Say so once per answer that ranks
or recommends, briefly. PSX restricts redistribution of its market data: keep downloaded
prices private and never publish them (no public repos, no shared artifacts with raw data).
