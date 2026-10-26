# PSX & MUFAP skill for Claude

Find out which Pakistan Stock Exchange shares, sectors and mutual funds are doing well, compare
companies side by side, test trading ideas on real history, and run a pretend PKR portfolio that
is proposed from those tests. Works in Claude on your phone, on the web, in Claude Code, or from a
terminal, with a dashboard served from your own computer.

- **Rank** your watchlist or **every listed share**: 1W to 1Y returns, volatility, drawdown,
  Sharpe, trend, lead/lag vs KSE-100, sector, **Shariah status** (KMI All Share) and **dividend
  yield**. Sector league table. MUFAP funds ranked inside each category.
- **Dividends**: full payout history per company, trailing-12-month yield, announced book
  closures, and an estimate of the next announcement from last year's pattern.
- **Backtest** moving-average, breakout, RSI and momentum strategies with next-day fills, costs,
  cash yield and tune-then-test-out-of-sample.
- **Propose a portfolio**: screen, backtest out of sample, pick the stocks whose strategy passed
  and is long today (sector-capped), and, after you say yes, buy them in the paper account. A
  daily review flags exits; dividends and bonus shares are credited automatically.
- **Dashboard**: overview, screener, compare up to 6 companies, portfolio, dividend calendar,
  funds. Light and dark, phone-friendly.

Python 3.8+, standard library only. Nothing to install. Nothing here can place a real order.

## Install

**Claude app (phone, web, desktop):** zip the `psx-mufap` folder and add it as a custom skill in
Claude's settings. Then ask, for example: *"Which Shariah-compliant cement stocks are doing best?"*,
*"Compare LUCK, DGKC and MLCF"*, *"Propose a paper portfolio from the whole market"*.

**Claude Code:**

```bash
git clone https://github.com/salmankhwaja/Day-Trader-PSX.git
cp -r Day-Trader-PSX/psx-mufap ~/.claude/skills/
```

or as a plugin: `/plugin marketplace add salmankhwaja/Day-Trader-PSX` then
`/plugin install psx-mufap@pk-market-skill`.

## Your computer: data, daily service and dashboard

```bash
git clone https://github.com/salmankhwaja/Day-Trader-PSX.git ~/Day-Trader-PSX
git clone git@github.com:salmankhwaja/pkmarket-data.git ~/pkmarket-data   # your PRIVATE data repo
cd ~/Day-Trader-PSX/psx-mufap/scripts
export PKM_HOME=~/pkmarket-data

# First time, whole market (15-20 minutes: one request a second to PSX):
python3 pkdata.py universe && python3 pkdata.py company --all && python3 pkdata.py psx --all
python3 pkdata.py payouts && python3 pkdata.py mufap
python3 rank.py stocks --all --top 20
python3 rank.py sectors

# Paper portfolio from backtests (review the proposal, then --apply)
python3 paper.py init --cash 1000000
python3 propose.py run --all
python3 propose.py run --all --apply

# Dashboard
python3 dashboard.py build && python3 dashboard.py serve    # http://127.0.0.1:8787
```

Then install the services (systemd user units, no root):

```bash
PKM_HOME=~/pkmarket-data PKM_SCOPE=all ./install_services.sh
```

- `pkm-daily.timer`, weekdays 17:15 Pakistan time: universe (Mondays), company pages (weekly
  cache), prices, payouts, MUFAP, credit paper dividends, review holdings, record the account
  value, a fresh proposal on Fridays (never booked without you), rebuild the dashboard, commit
  and push the private data repo.
- `pkm-dashboard.service`: the dashboard server, read-only, `127.0.0.1:8787`.

**Seeing the dashboard on your phone.** Install Tailscale on the computer and the phone, then
reinstall with `PKM_DASH_HOST=<the computer's Tailscale IP> PKM_DASHBOARD_PASSWORD='<long password>'`.
The server refuses any non-loopback address without a password (HTTP Basic, user `pkm`), serves
only its three files, accepts GET only, and sends strict security headers. It speaks plain HTTP,
so keep it on a private network (Tailscale encrypts the link); never expose it to the internet.
Alternatively, `dashboard.py build --standalone pkm.html` makes one file you can open anywhere.

## Using it from Claude on your phone

The phone app's sandbox blocks most websites. Claude tries a direct download, then fetches pages
with its web tools and imports them (`--from-file`). The MUFAP table works this way; PSX pages
may not. That is what the daily service is for: Claude reads the fresh data from your private
`pkmarket-data` repo, including the paper account (`paper/portfolio.json`).

## Repo layout

```
psx-mufap/                  the skill (this is what you install)
  SKILL.md                  instructions Claude follows
  scripts/pkdata.py         download / import prices, universe, company pages, payouts, MUFAP
  scripts/psxinfo.py        parsers for PSX company, index and payout pages; dividend maths
  scripts/rank.py           rank stocks (watchlist or all), sectors, funds
  scripts/backtest.py       strategies, metrics, out-of-sample checks
  scripts/propose.py        portfolio proposals from backtests; daily review
  scripts/paper.py          paper account: trades, funds, dividends, signals, daily marks
  scripts/dashboard.py      build and serve the dashboard
  scripts/daily_sync.sh     the daily pipeline
  scripts/install_services.sh  systemd timer + dashboard service
  dashboard/                index.html + app.js (Chart.js 4.4.1 from cdnjs, pinned with SRI)
  references/               strategy and data-source notes
tests/                      offline tests: synthetic prices, a synthetic 12-share market,
                            trimmed PSX/MUFAP page samples
```

Run the tests with `python3 -m unittest discover tests`.

## Data and terms

- PSX Data Portal (`dps.psx.com.pk`): prices, index constituents, company pages, payouts. PSX
  prohibits redistribution or commercial use of its market data without a licence. Use it for
  your own analysis, keep the data repo private, and do not publish the dashboard. The test
  price fixtures are synthetic.
- MUFAP (`mufap.com.pk`): daily fund NAVs and returns.
- Assumptions you can change in `config.json`: trading costs (20 bps a side), dividend
  withholding tax (15%), face value (Rs 10, with per-symbol exceptions), liquidity floor.

## Disclaimer

Research and education only, not investment advice. Backtests describe the past after
simplifying assumptions (no dividends in prices, estimated costs); passing one is not a forecast.

MIT licence.
