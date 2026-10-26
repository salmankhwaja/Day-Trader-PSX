# Day-Trader-PSX

**Rank, compare, backtest and paper-trade Pakistan Stock Exchange (PSX) shares and MUFAP mutual
funds, from a terminal, a dashboard, or by asking Claude.**

- **Rank** your watchlist or every listed share: returns from 1 week to 1 year, volatility,
  drawdown, Sharpe ratio, trend, lead or lag against the KSE-100, sector, **Shariah status**
  (KMI All Share index) and **dividend yield**. Sector league table. MUFAP funds ranked inside
  each category.
- **Dividends**: each company's payout history, trailing 12-month yield, announced book
  closures, and an estimate of the next announcement.
- **Backtest** moving-average, breakout, RSI and momentum strategies, with next-day fills,
  trading costs and an honest out-of-sample test.
- **Propose a paper portfolio** from those backtests, then review it daily. Dividends and bonus
  shares are credited automatically.
- **Your real portfolio**: every trade with its date, broker and actual charges (commission,
  taxes, fees); first-in-first-out lots per broker; realised and unrealised profit and loss after
  costs; dividends; costs by broker.
- **Sell / hold / buy suggestions with stop-losses**: each holding gets SELL, TRIM, REVIEW or
  HOLD with a trailing stop and target; buy ideas come from backtests, each with entry,
  stop-loss, target and a quantity sized to your risk.
- **Dashboard**: overview, screener, compare up to 6 companies, your portfolio, paper account,
  dividend calendar, funds. Works on a phone; light and dark.

Plain Python 3.8+, standard library only: nothing to `pip install`. **Nothing here can place a
real order.** Research and practice only, not investment advice.

## One repo: a Claude skill *and* runnable code

The `psx-mufap/` folder is both:

- a **Claude skill**: `SKILL.md` tells Claude how to use the tools, so you can just ask
  *"which Shariah-compliant cement stocks are doing best?"*;
- a **set of command-line tools** in `psx-mufap/scripts/` that you run yourself.

Claude runs exactly the same scripts you do, so there is one codebase to maintain.

## Your data stays on your machine

The code repo holds **no market data and no portfolio**. Everything the tools download or
create goes to a data folder, `~/pkmarket` by default (change it with `PKM_HOME=/path` or
`--home /path`):

```
~/pkmarket/
  config.json          your watchlist, costs, tax rate (pkdata.py init creates it)
  universe.json        every listed share + Shariah flags
  psx/<SYMBOL>.csv     daily prices
  companies/           sector, P/E, dividend history per company
  mufap/               daily fund snapshots + NAV history
  portfolio/ledger.json your real trades, brokers and charges
  advice/              daily sell/hold/buy suggestions
  paper/portfolio.json your paper account
  proposals/           portfolio proposals
  dashboard/           the built dashboard
```

PSX does not allow its market data to be republished, so never commit this folder to a public
repo. (`.gitignore` already excludes `pkmarket/`.)

## Quick start (Linux / macOS / WSL)

```bash
git clone https://github.com/salmankhwaja/Day-Trader-PSX.git
cd Day-Trader-PSX/psx-mufap/scripts

python3 pkdata.py init                 # creates ~/pkmarket/config.json; edit your watchlist there
python3 pkdata.py psx --watchlist      # prices for your watchlist + KSE-100
python3 pkdata.py company --watchlist  # sectors and dividend history
python3 pkdata.py universe             # Shariah (KMI) flags for every listed share
python3 pkdata.py payouts              # latest dividend announcements
python3 pkdata.py mufap                # today's mutual fund table

python3 rank.py stocks                 # rank your watchlist
python3 rank.py funds --category "Money Market"
python3 backtest.py compare OGDC       # every strategy on one share
python3 dashboard.py build && python3 dashboard.py serve   # open http://127.0.0.1:8787
```

### The whole market

```bash
python3 pkdata.py universe && python3 pkdata.py company --all && python3 pkdata.py psx --all
python3 rank.py stocks --all --top 20
python3 rank.py stocks --all --shariah --sector cement
python3 rank.py stocks --all --sort div_yield
python3 rank.py sectors
```

The first whole-market download takes 15–20 minutes, because the tools ask PSX politely
(one request a second). After that, company pages are cached for a week.

### Paper portfolio from backtests

```bash
python3 paper.py init --cash 1000000
python3 propose.py run --all             # screen, backtest, show the proposal (books nothing)
python3 propose.py run --all --apply     # buy the picks in the paper account
python3 propose.py review                # daily: HOLD or SELL each holding
python3 paper.py status
```

A stock is proposed only if its best strategy, tuned on the first 70% of its history, also did
well on the untouched last 30%: it beat a cash return, had a positive Sharpe ratio, lost less
than 35% at worst, and its signal says buy today. At most 2 picks come from any one sector.

### Your real portfolio, with buy and sell suggestions

```bash
python3 portfolio.py broker add AKD --commission-pct 0.15 --min-commission 50 --default
python3 portfolio.py buy OGDC 500 298 --broker AKD --date 2026-10-25 --commission 223.5 --taxes 29 --other 10
python3 portfolio.py sell OGDC 200 315 --broker AKD --date 2026-11-10 --commission 94.5
python3 portfolio.py import my-trades.csv     # date,side,symbol,qty,price,broker,commission,taxes,other,note
python3 portfolio.py cash deposit 500000      # optional: buy ideas then fit your cash
python3 portfolio.py holdings                 # average cost incl. charges, value, P/L, stop
python3 portfolio.py pnl --year 2026          # realised P/L per sale, after all charges
python3 portfolio.py fees                     # what each broker has cost you
python3 portfolio.py advise --all             # SELL / TRIM / REVIEW / HOLD + buy ideas with stops
```

Use the charges from your broker's contract note. Leave `--commission` out and it is estimated
from the broker's schedule and marked "estimated". Shares are held at a broker, so a sale uses
that broker's oldest shares first, and you can't sell shares you didn't hold at that broker on
that date.

How the suggestions work (all adjustable in `config.json`):

| Rule | Default |
|---|---|
| Stop-loss | 2.5 × the 14-day average daily move below entry, kept 5–15% below entry, then trailing up behind the highest close since you bought. Your own `portfolio.py stop SYMBOL PRICE` always wins. |
| Target | entry + 2 × (entry − stop) |
| SELL | last close at or below the stop |
| TRIM | one stock is over 25% of the portfolio (tells you how many to sell) |
| REVIEW | below its 50- and 200-day averages and over 5 points behind KSE-100 in 3 months |
| Buy ideas | the stocks that passed the backtest checks above and say buy today; quantity risks 1% of your capital between entry and stop, at most 25% in one stock, within your recorded cash |

The suggestions use the last close, not live prices, and are rules applied to past prices: not
investment advice. Nothing is ever ordered for you.

## Run it on a schedule (optional)

```bash
cd psx-mufap/scripts
./install_services.sh                                   # 07:00, Monday to Friday
PKM_SCHEDULE="07:00,04:00" ./install_services.sh        # twice a day
PKM_SCHEDULE="18:30" PKM_DAYS="Mon..Sat" ./install_services.sh
PKM_SCOPE=all PKM_SCHEDULE="04:00" ./install_services.sh  # whole market, overnight
```

Times are 24-hour Pakistan time (`PKM_TZ` to change), comma-separated; `PKM_DAYS` takes
`Mon..Fri`, `Mon,Wed,Fri`, `Mon..Sat` or `*` for every day. Run the script again to change the
schedule. PSX publishes closing prices after the market closes (about 15:30), so a run at 04:00
or 07:00 uses the previous session's close and is ready before the 09:30 open.

This installs two systemd user services (no root):

- **`pkm-daily.timer`**, at your times. Refreshes prices, company data, payouts and MUFAP;
  credits paper dividends; reviews the paper holdings; records the paper account value; lists
  dividends due on your real holdings (for you to confirm); writes your sell / hold / buy
  suggestions with stop-losses; makes a fresh paper proposal on Fridays; rebuilds the dashboard.
- **`pkm-dashboard.service`**: the dashboard server, read-only, on `127.0.0.1:8787`.

No systemd? Use cron, e.g. 07:00 and 04:00 on weekdays with the computer's clock on Pakistan
time: `0 4,7 * * 1-5 /path/to/psx-mufap/scripts/daily_sync.sh`.

### Seeing the dashboard on your phone

- **Simplest:** `python3 dashboard.py build --standalone pkm.html`, then send yourself the file
  and open it in the phone's browser.
- **Always up to date:** put the computer and phone on a private network such as Tailscale and
  reinstall with `PKM_DASH_HOST=<computer's Tailscale IP> PKM_DASHBOARD_PASSWORD='<long password>'`.
  The server refuses any address other than localhost without a password. It serves only its
  three files, accepts GET only, and sends strict security headers. It speaks plain HTTP, so never
  expose it to the open internet.

## Use it with Claude

**Claude app (phone, web, desktop):** download `psx-mufap.zip` from the
[releases page](https://github.com/salmankhwaja/Day-Trader-PSX/releases), or zip the
`psx-mufap` folder yourself (`zip -r psx-mufap.zip psx-mufap`), and add it as a custom skill in
Claude's settings. Then ask, for
example:

- *"Top 5 Shariah-compliant stocks by 3-month return"*
- *"Compare LUCK, DGKC and MLCF, including dividends"*
- *"Which money market funds did best over 90 days?"*
- *"Backtest a moving-average strategy on ENGRO"*
- *"Propose a paper portfolio from the whole market"*
- *"I bought 500 OGDC at 298 through AKD today, commission 223.50"*
- *"What should I sell, and what could I buy, with stop-losses?"*
- *"How much have I paid each broker this year, and what's my realised profit?"*

Claude's phone sandbox blocks most websites. Claude then fetches pages with its own web tools
and imports them. This works for the MUFAP table; PSX pages may stay out of reach. For full PSX
data on the phone, run the daily service on a computer and keep your data folder in **your own
private** git repo: set `PKM_HOME` to that repo and `PKM_GIT_PUSH=1`, and the pipeline commits and
pushes after each run. Claude can then read your data and paper account from it.

**Claude Code:**

```bash
cp -r Day-Trader-PSX/psx-mufap ~/.claude/skills/
# or: /plugin marketplace add salmankhwaja/Day-Trader-PSX, then /plugin install psx-mufap@pk-market-skill
```

## Settings

`~/pkmarket/config.json` (anything missing uses the default):

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
  "face_values": {}
}
```

| Setting | Meaning |
|---|---|
| `cost_bps_per_side` | commission + taxes + slippage per buy or sell, in basis points (20 = 0.2%) |
| `risk_free_annual` | what idle cash earns, e.g. `0.11` for an 11% money-market yield; strategies must beat it |
| `min_avg_volume` | with `--all`, skip shares trading fewer shares a day than this (60-day average) |
| `dividend_tax` | withholding tax on paper dividends; rates differ for filers and non-filers |
| `face_values` | dividend per share = percent × face value; Rs 10 unless listed here, e.g. `{"ABC": 5}` |

The defaults for costs, tax and face value are assumptions: set them to match your broker and
tax status.

## Repo layout

```
psx-mufap/                    the skill and the tools
  SKILL.md                    instructions Claude follows
  scripts/pkdata.py           download / import prices, universe, company pages, payouts, MUFAP
  scripts/psxinfo.py          parsers for PSX pages; dividend maths
  scripts/rank.py             rank stocks, sectors, funds
  scripts/backtest.py         strategies, metrics, out-of-sample checks
  scripts/propose.py          portfolio proposals and daily review
  scripts/paper.py            paper account: trades, funds, dividends, daily marks
  scripts/portfolio.py        your real portfolio: trades, brokers, charges, lots, P/L, dividends
  scripts/advice.py           stop-losses, sell/hold/trim rules, sized buy ideas
  scripts/dashboard.py        build and serve the dashboard
  scripts/daily_sync.sh       the daily pipeline
  scripts/install_services.sh systemd timer (your schedule) and dashboard service
  dashboard/                  index.html + app.js (Chart.js 4.4.1 from cdnjs, pinned with SRI)
  references/                 strategy and data-source notes
tests/                        offline tests on synthetic data and trimmed page samples
ci/                           GitHub Actions: tests, and a release zip on v* tags (see ci/README.md)
```

Run the tests with `python3 -m unittest discover tests`. They need no network.

## Data sources and terms

- **PSX Data Portal** (`dps.psx.com.pk`): daily prices, index members (All Share, KMI All
  Share), company pages, payouts. PSX prohibits redistribution or commercial use of its market
  data without a licence (marketdatarequest@psx.com.pk). These tools are for personal analysis:
  keep downloaded data private and don't publish dashboards built from it.
- **MUFAP** (`mufap.com.pk`): daily fund NAVs and returns.
- The PSX endpoints are undocumented and can change; the parsers fail loudly when they do.
  Details: `psx-mufap/references/data-sources.md`.

## Limits worth knowing

- Prices exclude dividends, so buy-and-hold returns of high payers are understated.
- No intraday highs and lows in the free PSX series, so no intraday stops.
- Bonus issues and splits show as price drops; `pkdata.py` warns about one-day falls of 30% or
  more.
- "Expected next dividend" is an estimate from last year's timing, not a company notice.
- Past performance and passing backtests do not predict returns.

## Contributing

Issues and pull requests are welcome. Please keep it standard-library Python, add a test for
any parser change (with a trimmed page sample in `tests/fixtures/`), and never commit real
PSX price data.

MIT licence.
