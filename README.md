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
- **Dashboard**: overview, screener, compare up to 6 companies, portfolio, dividend calendar,
  funds. Works on a phone; light and dark.

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

## Run it every day (optional)

```bash
cd psx-mufap/scripts
./install_services.sh                  # watchlist mode
PKM_SCOPE=all ./install_services.sh    # whole market
```

This installs two systemd user services (no root):

- **`pkm-daily.timer`**, weekdays at 17:15 Pakistan time. Refreshes prices, company data, payouts
  and MUFAP; credits paper dividends; reviews holdings; records the account value; makes a fresh
  proposal on Fridays (never booked without you); rebuilds the dashboard.
- **`pkm-dashboard.service`**: the dashboard server, read-only, on `127.0.0.1:8787`.

No systemd? Use cron: `15 17 * * 1-5 /path/to/psx-mufap/scripts/daily_sync.sh`.

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
  scripts/dashboard.py        build and serve the dashboard
  scripts/daily_sync.sh       the daily pipeline
  scripts/install_services.sh systemd timer and dashboard service
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
