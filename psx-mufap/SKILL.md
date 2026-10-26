---
name: psx-mufap
description: Rank Pakistan Stock Exchange (PSX) stocks and MUFAP mutual funds by performance, backtest trading strategies on PSX prices or fund NAVs, and run a PKR paper-trading account. Use when the user asks which PSX shares or Pakistani mutual funds are doing well, wants KSE-100 comparisons, fund category rankings, a strategy backtest, or to paper trade. Never places real orders.
---

# PSX & MUFAP: rank, backtest, paper trade

Plain Python 3.8+, standard library only, in `scripts/`. Every tool prints Markdown
tables that read well on a phone. Run them with `python3 scripts/<tool>.py ...`
from this skill's folder. All data and the paper account live in one folder, the
"home": `./pkmarket` unless `PKM_HOME` or `--home` says otherwise.

| Tool | Job |
|---|---|
| `pkdata.py` | Download or import PSX daily prices and the MUFAP fund table |
| `rank.py` | Rank stocks (returns, risk, trend, vs KSE-100) and funds (within category) |
| `backtest.py` | Test strategies with next-day fills, costs and out-of-sample checks |
| `paper.py` | Pretend PKR account: buy/sell shares, invest/redeem funds, follow signals |

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

Always tell the user the date of the data you used. `pkdata.py status` shows it.

## Step 2: answer "what is doing well?"

```
python3 scripts/rank.py stocks                     # top 10 of the watchlist by score
python3 scripts/rank.py stocks --sort 3m --top 5
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

## Step 4: paper trade

```
python3 scripts/paper.py init --cash 1000000
python3 scripts/paper.py buy OGDC 500                 # at the latest downloaded close
python3 scripts/paper.py invest "Alfalah Cash Fund - II" 200000
python3 scripts/paper.py signals --strategy momentum  # shows proposed orders only
python3 scripts/paper.py status
```

Rules:
- **Confirm before booking.** Show the user the orders from `signals` (or the trade they
  asked for) and only run `--apply`, `buy`, `sell`, `invest` or `redeem` after they say yes.
- If a fill price is flagged STALE, refresh the data first or tell the user.
- Nothing here can place a real order. If the user asks to trade for real, say this skill
  only paper trades and they should use their broker.
- The account is `pkmarket/paper/portfolio.json`. Claude's sandbox may not keep files
  between chats: at the end of a session that changed the account, save the file where the
  user keeps it (their private GitHub repo if connected, otherwise send it to them) and tell
  them where it went. At the start of a session, restore it from there before running
  `paper.py`.

## Settings

`pkmarket/config.json` (optional; anything missing uses the default):

```json
{
  "watchlist": ["OGDC", "PPL", "MARI", "HUBC", "LUCK", "MCB", "MEBL", "ENGRO", "FFC", "SYS"],
  "benchmark": "KSE100",
  "cost_bps_per_side": 20,
  "lot_size": 1,
  "risk_free_annual": 0.0,
  "paper_starting_cash": 1000000
}
```

`cost_bps_per_side` and `lot_size` are assumptions: ask the user what their broker charges
if it matters. Sources and data caveats: `references/data-sources.md`.

## Boundaries

This is research and education, not investment advice. Say so once per answer that ranks
or recommends, briefly. PSX restricts redistribution of its market data: keep downloaded
prices private and never publish them (no public repos, no shared artifacts with raw data).
