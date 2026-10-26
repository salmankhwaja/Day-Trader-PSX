---
name: psx-mufap
description: Rank Pakistan Stock Exchange (PSX) stocks (watchlist or every listed share, by sector, Shariah/KMI status and dividend yield) and MUFAP mutual funds, backtest strategies, propose a paper portfolio from backtests, keep the user's real portfolio ledger (trades, brokers, commissions, P/L) with sell/hold/buy suggestions and stop-losses, track dividends and book closures, and build a comparison dashboard. Use when the user asks which PSX shares, sectors or Pakistani mutual funds are doing well, about dividends or Shariah compliance of PSX stocks, wants to compare companies, record a trade they made, see their portfolio or P/L, get buy/sell suggestions with stop-losses, backtest, paper trade or see the dashboard. Never places real orders.
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
| `portfolio.py` | The user's REAL portfolio: trades, brokers, commissions, lots, P/L, dividends, cash; `advise` |
| `pkm.py` | Menu launcher (also passes through: `pkm.py rank stocks`); the user may run it on Android in Pydroid 3 or Termux |
| `daily.py` | The daily pipeline in pure Python; `daily_sync.sh` and the systemd timer call it |
| `profiles.py` | The four risk styles and every buy/sell variable, with descriptions |
| `risk.py` | Risk quiz, switch style, show/override settings, position sizing, portfolio risk |
| `sip.py` | SIP calculator: plan (step-up, inflation, lump sum) and goal; rates from profile mix, fund or share |
| `funds.py` | MUFAP fund suggestions by risk profile (`advise`), and HOLD/REVIEW for funds the user holds (`review`) |
| `brokers.json` | Published PSX broker tariffs and pass-through charges, with sources (used by `portfolio.py broker`) |
| `advice.py` | Stop-losses, sell/hold/trim suggestions and sized buy ideas (used by `portfolio.py advise`) |
| `dashboard.py` | Build the visual dashboard (compare, screener, portfolio, dividends, funds) and serve it |
| `daily_sync.sh`, `install_services.sh` | The daily pipeline and its systemd timer, for the user's computer |

Data comes from the PSX Data Portal (`dps.psx.com.pk`: daily prices, index members, company
pages, payouts) and MUFAP (fund NAVs and returns), end of day. Say so when asked where the
numbers come from.

## Before every piece of advice: last fetch, fresh fetch, or live?

Every time the user asks for advice (what to buy, sell or hold, one share, funds, rankings,
portfolio risk), **first ask which prices to use**, stating how old the data on file is
(`python3 scripts/pkdata.py status`):

- **last fetch** (`--no-fetch`): the end-of-day data on file;
- **fresh fetch** (`--fetch`): download end-of-day data for the shares involved first;
- **live** (`--live`): today's PSX prices (the portal's market watch), laid over the history.
  Suggest it during market hours (Mon-Fri, about 09:30-15:30 Pakistan time) or before an order.

Ask every time, unless the user has given a standing choice in this conversation ("always use
live"). Then run the command with that flag so it never asks or fetches silently:

```
python3 scripts/portfolio.py advise --live         # or --fetch / --no-fetch
python3 scripts/portfolio.py check MEBL --live
python3 scripts/pkdata.py live MEBL OGDC           # just the live prices
```

Every advice command takes the three flags (`portfolio.py advise|check`, `rank.py
stocks|funds`, `funds.py advise|review`, `propose.py run|review`, `risk.py portfolio`). Fetching
is the only step that uses the network; all calculations then use the data in hand. The output
starts with "Based on …" (live time and market open/closed, or the end-of-day date): repeat it in
your answer. If a fetch or live request fails (sandbox), it falls back to the last fetch and says
so; tell the user. Funds have no live prices (daily NAVs). Live quotes can lag the exchange.

## The watchlist

The watchlist (config.json "watchlist") is where rankings, buy ideas and daily downloads start.
When the user names shares to follow, drop or replace, change it rather than editing JSON:

```
python3 scripts/watchlist.py                          # show it
python3 scripts/watchlist.py add LUCK DGKC --fetch    # add (checked against listed shares) and download
python3 scripts/watchlist.py remove TRG
python3 scripts/watchlist.py set OGDC PPL MARI        # replace
python3 scripts/watchlist.py add --top 5 --sector cement --shariah
python3 scripts/watchlist.py add --holdings
```

Say what changed, and mention any symbol that was refused as not listed.

## A second opinion: PakistaniBulls

If PakistaniBulls signals are on file (`signals.py show`), advice and `check` print a SECOND
OPINION table (and the dashboard a "PakistaniBulls says" column): their signal (BUY, SELL, STAY
LONG, STAY IN CASH, SHORT, STAY SHORT), signal price, flip level, pattern, and whether it agrees.
Present it as a different method for comparison, never as the decider, and point out
disagreements. To add one:

- The user saved their signal list page (members' or free): `signals.py pakistanibulls --from-file FILE`.
- Direct download of the free list: their terms allow one copy for personal use only. Quote that
  to the user and ask; only if they agree run `signals.py pakistanibulls --accept-terms`, then
  `--fetch`. Never ask for or handle their PakistaniBulls password, and never publish or share the
  signals (no public artifacts, no commits).
- If you fetch their page with your own web tool, ask for the full HTML or Markdown, save it, and
  import it with `--from-file` (personal use only, same rule).

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
2. **PSX:** since late 2026 `https://dps.psx.com.pk/timeseries/eod/<SYMBOL>` returns 404
   unless the request carries the portal's session cookie and key (`window.__ps._k` from any
   portal page, sent as `X-Req-Id`). `pkdata.py` does this itself; a plain web fetch tool can't,
   so don't promise PSX prices through one. If the user saves the response themselves (company
   page › browser developer tools › Network › the `eod` request), import it with
   `pkdata.py psx <SYMBOL> --from-file <file>`. Company pages (`/company/<SYMBOL>`) still fetch
   normally.
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

## Step 6: the user's real portfolio

`portfolio.py` is a ledger of what the user actually bought and sold, at which broker, and
what it cost. It never contacts a broker. Keep it separate from the paper account.

Recording trades the user tells you about ("I bought 500 OGDC at 298 through AKD yesterday"):
- Ask for anything missing that matters: the date, the broker, and the actual charges from the
  contract note (commission, taxes such as CVT/SST, other fees such as CDC/NCCPL). If they don't
  have the charges, record without `--commission` and say it was estimated from the broker's
  schedule.
- If they name a stop-loss, record it with `--stop`; if not, say a stop will be computed daily.
- Record the time if they give one (`--time HH:MM`, Pakistan time); recorded today without one,
  it's stamped with the current time.
- Read the trade back in one line before recording it, then run the command:

```
python3 scripts/portfolio.py broker presets             # published tariffs: akd, js-global, scs, ktrade, ...
python3 scripts/portfolio.py broker add AKD --preset akd --default
python3 scripts/portfolio.py broker add MyBroker --commission-pct 0.12 --per-share 0.03 --sales-tax-pct 13
python3 scripts/portfolio.py buy OGDC 500 298 --broker AKD --date 2026-10-25 --commission 223.5 --taxes 29 --other 10
python3 scripts/portfolio.py buy OGDC 500 298 --broker AKD --stop 280   # with the user's own stop-loss
python3 scripts/portfolio.py fund-buy "Alfalah Cash Fund - II" 200000 --nav 106.73   # mutual funds
python3 scripts/portfolio.py fund-sell "Alfalah Cash Fund - II" all --nav 108.10
python3 scripts/portfolio.py sell OGDC 200 315 --broker AKD --date 2026-11-10 --commission 94.5
python3 scripts/portfolio.py import trades.csv        # date,side,symbol,qty,price,broker,commission,taxes,other,note
python3 scripts/portfolio.py cash deposit 500000      # optional: lets buy ideas respect available cash
python3 scripts/portfolio.py holdings --live --lots   # GREEN / RED per holding and per purchase
python3 scripts/portfolio.py holdings | pnl | fees | trades
python3 scripts/portfolio.py delete ID                # fix a mistake
python3 scripts/portfolio.py stop OGDC 280            # the user's own stop-loss; `auto` to go back
python3 scripts/portfolio.py dividends [--apply]      # dividends due from book closures; confirm amounts first
```

Finqalab users: `broker add Finqalab --preset finqalab` (0.25% or Rs 0.03/share, whichever is
higher, as reported; one-time PKR 476 NCCPL fee). Its app has market, limit and stop-loss
(trigger + limit) orders, stop-losses valid for one day only, and no public API.

When the user asks how to set the trades up in their app, run `portfolio.py orders` (after the
fetch question) and give the tickets: side, order type, qty, trigger, limit, and how long each
order lasts. Never place, or offer to place, an order yourself.

Broker presets (`brokers.json`) hold each broker's published commission (per share or percent,
whichever is higher, with price slabs), plus sales tax on commission (13%, Sindh), CDC
Rs 0.005/share and exchange/regulator levies, each with a source link and a confidence note.
When the user's broker isn't listed, or they have a negotiated rate, add it by hand from their
commission sheet. Charges not given on a trade are estimated from the broker's schedule and
marked estimated; the contract note always wins.

Sales are matched first-in, first-out against that broker's lots; P/L is after every charge.
A sale of shares not held at that broker on that date is refused. Capital gains tax is not
computed (it depends on filer status and holding period); record it with `--taxes` if wanted.

Suggestions (after asking about fetching, see above):

```
python3 scripts/portfolio.py advise --no-fetch|--fetch|--live           # watchlist buy ideas
python3 scripts/portfolio.py advise --all --shariah --live              # whole market, Shariah only
python3 scripts/portfolio.py check MEBL --live                          # one share: verdict, stop, target, size
python3 scripts/portfolio.py check MEBL --entry 250 --stop 232 --no-fetch   # with the user's own prices
```

For each holding: SELL (close at or below its stop), TRIM (over 25% of the portfolio, with a
quantity), REVIEW (falling trend and lagging KSE-100), or HOLD, with stop and target, plus a
note when a book closure is near. Then up to 3 buy ideas: the shares that passed the
backtest gates and are long today, each with entry, stop-loss, target, a quantity that risks
1% of capital between entry and stop (capped at 25% per stock and at recorded cash), and the
estimated commission at the default broker.

How to present them:
- **Always include the price calculator** for every share you advise on (it's in the output's
  PRICE CALCULATOR section, and in `--json` as `calc`): shares and cost incl. charges, rupees
  lost if it falls to the stop, rupees gained at the target, reward-to-risk, the win rate it
  needs to be worth it, and the break-even price. For holdings, also what selling today or at
  the stop makes or loses against what they paid. When the user asks about a single share,
  run `portfolio.py check SYMBOL` and give its verdict with the calculator.
- When the user asks how their portfolio is doing, use `holdings` (ask last fetch / fresh / live
  first) and show each share as **GREEN** (profit) or **RED** (loss) if sold now, after charges on
  both sides: what they paid and when (date, time) against the price now and when it's from (live
  time, or the 15:30 close). Mention purchases of the same share that differ in colour.
- Lead with any SELL or TRIM, then buy ideas, each with its stop-loss. Show why (the rule
  that fired, the out-of-sample result) in plain words.
- Prices are the last close: say so, and that the user should check the live price.
- Say once that these are rule-based suggestions from past prices, not investment advice,
  and that you are not a licensed adviser. Never place or promise to place an order.
- Stops and sizing rules live in config.json (`stop_atr_mult`, `min_stop_pct`, `max_stop_pct`,
  `target_r`, `risk_per_trade`, `max_position_pct`); explain them if asked.
- The ledger is the user's financial record: never publish it or commit it to a public repo.

**Funds.** For "which mutual funds should I hold", ask (or infer from the conversation) their
risk appetite and whether they want Shariah-compliant funds, then:

```
python3 scripts/funds.py advise --risk low|medium|high [--shariah]
python3 scripts/funds.py review        # the funds they hold: HOLD, or REVIEW (bottom third of category)
```

Explain the category first (what it invests in, how risky it is), then the top funds and their
30-day, 90-day and 1-year returns. Say that returns exclude sales loads and that annualised
(money market, income) and absolute (equity, mixed) returns can't be compared.

## Step 7: risk style, risk calculator, SIP

Every suggestion follows the user's **risk style** (`risk_profile`: conservative, moderate,
aggressive, very_aggressive). It sets ranking weights, backtest gates, stop distances, position
sizes, the holdings cap, the cash reserve and the total risk budget (`profiles.py`). Mention the
style when giving advice ("as a moderate investor, …").

- **No style chosen yet, and they ask for advice?** Offer the quiz first: ask the eight questions
  in `risk.py` (QUESTIONS) in conversation, then run
  `risk.py quiz --answers a,b,c,d,e,f,g,h`, show the result, and `--save` only if they agree.
  The style is the lower of capacity and willingness; explain which one set it.
- **"Make me more aggressive"** → `risk.py profile aggressive`. **"…but no more than 6 shares"** →
  `risk.py set max_holdings 6`. Show `risk.py settings` when they ask what drives the advice.
- **"How much should I buy?"** → `risk.py position --entry E --stop S` (uses their capital and
  risk_per_trade). **"How much am I risking?"** → `risk.py portfolio`: money lost if every stop
  hits, value-at-risk, volatility, beta, diversification, allocation vs target, and warnings.
- **"Maximise my profit"**: be honest. More expected return means more risk; the right style
  is the riskiest one they can live with. Never promise returns.
- **SIP**: `sip.py plan --monthly M --years Y [--step-up %] [--inflation %] [--lump X]`, or
  `sip.py goal --target T --years Y`. Say where the rate came from (the output says), and show
  the ±3-point range. Rates from `--fund` or `--symbol` are past returns, not forecasts.

## Step 8: the dashboard

```
python3 scripts/dashboard.py build                     # <home>/dashboard/ (index.html, app.js, data.json)
python3 scripts/dashboard.py build --standalone pkm.html   # one self-contained file
python3 scripts/dashboard.py serve                     # http://127.0.0.1:8787
```

Views (also a Risk & SIP tab with the style, portfolio risk and a live SIP calculator): Overview (KSE-100, sectors, top ranked, upcoming dividends), My portfolio (real holdings
with action, stop and target, buy ideas, allocation, costs by broker, realised P/L, dividends), Screener (filter by sector,
Shariah, yield; tick up to 6 to compare), Compare (rebased prices, returns, risk, valuation,
dividends side by side), Paper (value vs KSE-100, allocation, holdings with review action and next
dividend, latest proposal), Dividends (calendar, top yields), Funds (MUFAP by category).

The page shows the data's date and, when it's older than today, asks *Fetch now* or *Use stored
data*; the user's choice can be remembered in a cookie (`pkm_refresh`). Fetching from the page
needs `dashboard.py serve --allow-refresh`. A **Live prices** switch (`--allow-live`, cookie
`pkm_live`) shows live prices, revalues holdings, reruns the price calculator and flags stops hit,
updating every minute while the market is open. Both are on by default from the installers when
the server is local only; the standalone file can do neither and names the command instead.

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
