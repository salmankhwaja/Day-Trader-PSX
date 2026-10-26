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
  taxes, fees), estimated from published broker tariffs when you don't have them;
  first-in-first-out lots per broker; mutual fund holdings; realised and unrealised profit and
  loss after costs; dividends; costs by broker.
- **Sell / hold / buy suggestions with stop-losses**: each holding gets SELL, TRIM, REVIEW or
  HOLD with a trailing stop and target; buy ideas come from backtests, each with entry,
  stop-loss, target and a quantity sized to your risk. **Fund suggestions** by risk profile,
  and a check on the funds you hold.
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
  portfolio/ledger.json your real trades, fund holdings, brokers and charges
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
python3 pkdata.py init        # creates ~/pkmarket/config.json: put your watchlist in it
```

Every command below runs from `psx-mufap/scripts`. Add `--help` to any of them for all options.
Prefer a menu? `python3 pkm.py` asks you questions instead.

**On an Android phone?** Follow [Run it on Android](#run-it-on-android-pydroid-3-or-termux), a
start-to-finish guide that ends with the dashboard on your home screen.

## Command cheat sheet

### 1. Fetch data

```bash
# Your watchlist (fast: a minute or two)
python3 pkdata.py psx --watchlist          # daily prices for the watchlist + KSE-100
python3 pkdata.py company --watchlist      # sector, P/E, dividend history (cached 7 days)
python3 pkdata.py universe                 # every listed share + Shariah (KMI) flags
python3 pkdata.py payouts                  # latest dividend announcements and book closures
python3 pkdata.py mufap                    # today's MUFAP table: every fund's NAV and returns

# The whole market (first time 15-20 minutes: one polite request a second)
python3 pkdata.py universe && python3 pkdata.py company --all && python3 pkdata.py psx --all

# Odd symbols, or a page you saved yourself
python3 pkdata.py psx LUCK DGKC MLCF
python3 pkdata.py psx OGDC --from-file ogdc.json
python3 pkdata.py status                   # what is on disk and how fresh it is
```

### 2. Set the schedule

```bash
./install_services.sh                                     # 07:00, Monday to Friday
PKM_SCHEDULE="07:00,04:00" ./install_services.sh          # 07:00 and 04:00
PKM_SCHEDULE="18:30" PKM_DAYS="Mon..Sat" ./install_services.sh
PKM_SCOPE=all PKM_SCHEDULE="04:00" ./install_services.sh  # whole market, overnight
systemctl --user list-timers pkm-daily.timer              # next run
systemctl --user start pkm-daily.service                  # run it now
journalctl --user -u pkm-daily -n 100                     # last run's log
```

Times are 24-hour Pakistan time, comma-separated. `PKM_DAYS` takes `Mon..Fri`, `Mon,Wed,Fri`,
`Mon..Sat` or `*`. Run the script again to change the schedule. Details:
[Run it on a schedule](#run-it-on-a-schedule-optional).

### 3. Advice: which stocks to hold, buy or sell

```bash
python3 rank.py stocks                         # your watchlist, best first
python3 rank.py stocks --all --top 20          # the whole market
python3 rank.py stocks --all --shariah --sector cement
python3 rank.py stocks --all --sort div_yield  # highest dividend yield
python3 rank.py sectors                        # sector league table

python3 portfolio.py advise                    # your holdings: SELL / TRIM / REVIEW / HOLD with stop-loss,
                                               #   plus up to 3 buy ideas with entry, stop, target, quantity
python3 portfolio.py advise --all --shariah --buy 5   # buy ideas from the whole market, Shariah only

python3 backtest.py compare OGDC               # how each strategy did on one share
python3 backtest.py run LUCK --strategy breakout --optimize
```

### 4. Advice: which MUFAP funds to hold

```bash
python3 funds.py advise --risk low             # money market: stable, liquid
python3 funds.py advise --risk medium          # income, asset allocation, balanced, fund of funds
python3 funds.py advise --risk high --shariah  # equity and index funds, Shariah-compliant
python3 funds.py review                        # the funds you hold vs their category: HOLD or REVIEW
python3 rank.py categories                     # every category: median and best returns
python3 rank.py funds --category "Money Market" --top 10
```

Funds are only compared inside their own category, on 30-day, 90-day and 1-year returns.

### 5. Set up your brokers (published tariffs included)

```bash
python3 portfolio.py broker presets                        # published tariffs of PSX brokers, with sources
python3 portfolio.py broker add AKD --preset akd --default # start from a preset
python3 portfolio.py broker import js-global,scs            # load several presets at once
python3 portfolio.py broker add MyBroker --commission-pct 0.12 --per-share 0.03 \
        --min-commission 0 --sales-tax-pct 13               # or type in your own commission sheet
python3 portfolio.py broker list
```

Presets (in [`psx-mufap/brokers.json`](psx-mufap/brokers.json)) cover AKD, MRA, JS Global,
Khanani, KTrade, Topline, SCS, Optimus, Arif Habib, Next Capital and Sherman, plus the PSX
minimum. Each preset gives its commission (per share or percent, whichever is higher, with
price slabs where published), plus sales tax on commission, CDC per-share charge and exchange
and regulator levies. Each preset also carries its source link and how sure we are of it.
Commissions are negotiable, so your signed commission sheet beats any preset: edit the file,
pass your own with `--file`, or add the broker by hand.

### 6. Record a buy or sell (with or without a stop-loss)

```bash
# Buy without a stop-loss: one is computed and updated daily by `advise`
python3 portfolio.py buy OGDC 500 298 --broker AKD --date 2026-10-25

# Buy with your own stop-loss
python3 portfolio.py buy OGDC 500 298 --broker AKD --date 2026-10-25 --stop 280

# Use the exact charges from your contract note (otherwise they are estimated and marked so)
python3 portfolio.py buy MCB 100 300 --broker AKD --commission 45 --taxes 5.85 --other 1.75

# Change or remove a stop later
python3 portfolio.py stop OGDC 285       # your stop
python3 portfolio.py stop OGDC auto      # back to the computed, trailing stop

# Sell some or all
python3 portfolio.py sell OGDC 200 315 --broker AKD --date 2026-11-10 --commission 94.5
python3 portfolio.py sell OGDC all 320 --broker AKD

# Mutual funds
python3 portfolio.py fund-buy "Alfalah Cash Fund - II" 200000 --nav 106.73 --load-pct 0
python3 portfolio.py fund-sell "Alfalah Cash Fund - II" all --nav 108.10

# Dividends, cash, bulk import, corrections
python3 portfolio.py dividends            # dividends due from book closures (then --apply)
python3 portfolio.py dividend OGDC 3825   # or record the exact net amount you received
python3 portfolio.py cash deposit 500000  # optional: buy ideas then fit your cash
python3 portfolio.py import my-trades.csv # date,side,symbol,qty,price,broker,commission,taxes,other,note,stop
python3 portfolio.py trades               # the ledger, with ids
python3 portfolio.py delete 7             # remove entry #7
```

### 7. See your portfolio

```bash
python3 portfolio.py holdings          # shares and funds: average cost incl. charges, value, P/L, stop
python3 portfolio.py pnl --year 2026   # realised profit per sale and redemption, after all charges
python3 portfolio.py fees              # what each broker has cost you
python3 portfolio.py export trades.csv
python3 dashboard.py build && python3 dashboard.py serve   # http://127.0.0.1:8787, tab "My portfolio"
```

## How the suggestions work

**Stocks** (`portfolio.py advise`). Every setting is in `config.json`.

| Rule | Default |
|---|---|
| Stop-loss | 2.5 × the 14-day average daily move below entry, kept 5–15% below entry, then trailing up behind the highest close since you bought. Your own stop (`--stop` on the buy, or `portfolio.py stop`) always wins. |
| Target | entry + 2 × (entry − stop) |
| SELL | last close at or below the stop |
| TRIM | one stock is over 25% of the portfolio (tells you how many to sell) |
| REVIEW | below its 50- and 200-day averages and over 5 points behind KSE-100 in 3 months |
| HOLD | none of the above; shows the distance to the stop and notes an upcoming book closure |
| Buy ideas | stocks whose best strategy, tuned on the first 70% of their history, also did well on the untouched last 30% (beat a cash return, positive Sharpe ratio, drawdown under 35%) and say buy today. Quantity risks 1% of your capital between entry and stop, at most 25% in one stock, within your recorded cash. |

**Funds** (`funds.py`). Risk profiles map to MUFAP categories (low: money market; medium:
income, aggressive fixed income, asset allocation, balanced, fund of funds; high: equity, index
trackers). Within a category, funds rank on the average percentile of their 30-day, 90-day and
1-year returns. Funds with a NAV more than 5 days old are left out. A fund you hold is marked
REVIEW when it sits in the bottom third of its category; the leaders are named.

All suggestions use the last close or NAV, not live prices. They are rules applied to past
data, not investment advice. Nothing is ever ordered for you.

### Paper trading (practice)

```bash
python3 paper.py init --cash 1000000
python3 propose.py run --all             # screen, backtest, show the proposal (books nothing)
python3 propose.py run --all --apply     # buy the picks in the paper account
python3 propose.py review                # HOLD or SELL each paper holding
python3 paper.py status
```

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

## Run it on Android (Pydroid 3 or Termux)

**Everything on your phone, start to finish:** data, rankings, advice, your portfolio and the
dashboard, with no computer. It takes about 20 minutes on Wi-Fi.

The guide uses **Termux**, a free Linux terminal for Android, because it can run updates on a
timer and keep the dashboard running. If you only want to run things by hand, the
[Pydroid 3 shortcut](#no-timer-needed-pydroid-3-instead) at the end is simpler.

**You need:** an Android 7 or newer phone, about 500 MB free, Wi-Fi for the first download,
and Chrome or another browser.

### Step 1. Install three apps from F-Droid

The Play Store version of Termux is outdated, so get these from F-Droid:

1. In the phone's browser, open **f-droid.org** and download and install the **F-Droid** app
   (allow "install unknown apps" for your browser when Android asks).
2. In F-Droid, search for and install:
   - **Termux**: the terminal.
   - **Termux:Widget**: home-screen buttons.
   - **Termux:Boot**: restarts everything after the phone reboots.
3. Open **Termux:Boot** once, so Android lets it run at start-up. Then open **Termux**.

### Step 2. Install Python and the code

Type these in Termux (long-press to paste), one line at a time:

```bash
pkg update -y && pkg install -y python git
termux-setup-storage
```

`termux-setup-storage` shows a permission prompt: tap **Allow**. Your data will live in
**Internal storage › pkmarket**, where your Files app and backups can see it. Then:

```bash
git clone https://github.com/salmankhwaja/Day-Trader-PSX.git
bash Day-Trader-PSX/psx-mufap/scripts/android_setup.sh
```

The setup script:
- installs the timer tools;
- creates your settings file;
- schedules the daily update for **07:00, Monday to Friday**;
- starts the dashboard in the background;
- adds home-screen shortcuts, and makes everything restart after a reboot.

If it asks you to restart Termux, type `exit`, open Termux again, and run the same `bash` line
again.

Want other times? Run it again with your choice, e.g. twice a day, or the whole market:

```bash
PKM_SCHEDULE="07:00,04:00" bash Day-Trader-PSX/psx-mufap/scripts/android_setup.sh
PKM_SCOPE=all PKM_SCHEDULE="04:00" bash Day-Trader-PSX/psx-mufap/scripts/android_setup.sh
```

Times use the phone's clock and time zone.

### Step 3. Let it run in the background

Android stops background apps to save battery. So the 07:00 update actually happens:

- **Settings › Apps › Termux › Battery › Unrestricted** (wording varies by phone: look for
  "Battery optimisation" or "Background usage").
- Leave Termux's notification in place; it shows Termux is awake.

### Step 4. Your watchlist and broker

Open the menu:

```bash
cd ~/Day-Trader-PSX/psx-mufap/scripts && python pkm.py
```

1. Choose **13 Settings** › change the watchlist, e.g. `OGDC,PPL,MARI,HUBC,LUCK,MCB,MEBL,ENGRO,FFC,SYS`.
2. Choose **10 Brokers**. It lists the published broker tariffs. Answer **y** to add yours,
   e.g. name `AKD`, preset `akd`, and make it the default. If your rate is different, leave the
   preset blank and type your commission sheet's numbers.

### Step 5. First download

Still in the menu:

- **1 Fetch data: my watchlist + funds**: about 2 minutes.
- **2 Fetch data: the whole market**: optional, 15–20 minutes and about 200 MB, so stay on
  Wi-Fi and keep the screen on. You need it for whole-market rankings, sectors and buy ideas
  from every share.

### Step 6. Put in what you already own

- **6 Record a BUY** for each holding. The prompts are:
  - symbol, quantity, price, broker and date;
  - the charges from your contract note (leave blank to estimate them);
  - your own stop-loss price (leave blank and one is computed and updated daily).
- **8 Record a mutual fund buy / sell** for each fund you hold.
- Many trades? Put them in a CSV file in **Internal storage › pkmarket** and import it:

  ```bash
  python portfolio.py import /storage/emulated/0/pkmarket/my-trades.csv
  ```

  The columns are `date,side,symbol,qty,price,broker,commission,taxes,other,note,stop`.

### Step 7. Open your dashboard

In Chrome go to **http://127.0.0.1:8787**, then Chrome menu › **Add to Home screen**. You now
have a dashboard icon:

- **Overview**: KSE-100, sectors, top-ranked shares, dividends coming up.
- **Screener**: filter by sector, Shariah, yield; tick shares to compare.
- **Compare**: up to 6 companies side by side, with dividends.
- **My portfolio**: what to sell, trim or hold, each with its stop-loss and target; buy ideas
  with quantity; your funds; costs by broker; realised profit and loss.
- **Paper**, **Dividends**, **Funds**.

The address only works on this phone (it never leaves the device). If the page doesn't load,
open Termux once, which restarts the dashboard service.

### Step 8. Everyday use

- **Every weekday at 07:00** prices, dividends, advice and the dashboard refresh by themselves.
  Open the dashboard icon to see what changed.
- **Home-screen buttons:** long-press the home screen › Widgets › **Termux:Widget**. It
  gives you:
  - **PSX-menu**: record a trade, get advice.
  - **PSX-update**: refresh now.
  - **PSX-dashboard**: open the dashboard.
- **Bought or sold something?** PSX-menu › **6** or **7**. The dashboard shows it after the next
  update, or straight away if you tap PSX-update.
- **Advice in text:** PSX-menu › **4** for stocks, with stop-losses; **5** for mutual funds.

### Step 9. Keep it safe and up to date

- **Back up your trade record:** copy `Internal storage › pkmarket › portfolio/ledger.json` to
  Google Drive or your computer now and then. It's the one file you can't download again.
- **Get the latest version of the code:**

  ```bash
  cd ~/Day-Trader-PSX && git pull
  ```

  Your data isn't touched.
- **See what the last update did:** open `Internal storage › pkmarket › daily.log`.

### If something goes wrong

| Problem | Fix |
|---|---|
| "Permission denied" for /storage/emulated/0 | Run `termux-setup-storage`, tap Allow, run the setup script again |
| The 07:00 update didn't happen | Battery set to Unrestricted (Step 3)? Run `sv-enable crond`; check `crontab -l` shows the `pkm-daily` lines |
| Dashboard page won't load | Open Termux; or run `sv-enable pkm-dashboard`; or use the one-file version: menu **12**, then open `pkmarket/dashboard.html` from the Files app |
| A download "FAILED" | The PSX or MUFAP site was busy or down: tap PSX-update later. One failed share doesn't stop the rest |
| Charts are blank | The charts library loads from the internet: check the phone is online |
| Wrong time zone for the timer | The timer uses the phone's clock: set Pakistan time, or adjust `PKM_SCHEDULE` |

### No timer needed? Pydroid 3 instead

1. Install **Pydroid 3** from the Play Store.
2. On this GitHub page tap **Code › Download ZIP**, and extract it into **Internal storage › Download**.
3. In Pydroid: folder icon › open `Download/Day-Trader-PSX-main/psx-mufap/scripts/pkm.py` ›
   **▶ Run**. Allow storage access when asked.
4. Follow Steps 4 to 6 above in the menu. Choose **11** whenever you want fresh data.
5. For the dashboard, choose **12**. Then in the Files app open
   **pkmarket › dashboard.html** with Chrome.

Pydroid can't run on a timer or keep the dashboard server running in the background; that's
what Termux adds.

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
- *"Which Shariah money market funds should I consider, and how do mine compare?"*
- *"Add my broker: 0.12% or 3 paisa a share, whichever is higher, Sindh sales tax"*

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
  "face_values": {},
  "stop_atr_mult": 2.5,
  "min_stop_pct": 0.05,
  "max_stop_pct": 0.15,
  "target_r": 2.0,
  "risk_per_trade": 0.01,
  "max_position_pct": 0.25
}
```

| Setting | Meaning |
|---|---|
| `cost_bps_per_side` | commission + taxes + slippage per buy or sell, in basis points (20 = 0.2%) |
| `risk_free_annual` | what idle cash earns, e.g. `0.11` for an 11% money-market yield; strategies must beat it |
| `min_avg_volume` | with `--all`, skip shares trading fewer shares a day than this (60-day average) |
| `dividend_tax` | withholding tax on paper dividends; rates differ for filers and non-filers |
| `face_values` | dividend per share = percent × face value; Rs 10 unless listed here, e.g. `{"ABC": 5}` |
| `stop_atr_mult`, `min_stop_pct`, `max_stop_pct` | how far below entry the stop-loss sits (see above) |
| `target_r` | target = entry + this × (entry − stop) |
| `risk_per_trade` | share of capital lost if a buy idea hits its stop (0.01 = 1%) |
| `max_position_pct` | most of the portfolio in one stock before TRIM (0.25 = 25%) |

Broker charges are not in `config.json`: they live with each broker in your ledger (see
[Set up your brokers](#5-set-up-your-brokers-published-tariffs-included)).

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
  scripts/funds.py            MUFAP fund suggestions by risk profile; review of funds you hold
  brokers.json                published PSX broker tariffs and pass-through charges, with sources
  scripts/dashboard.py        build and serve the dashboard
  scripts/pkm.py              a menu launcher for everything (phones, or if you prefer menus)
  scripts/daily.py            the daily pipeline, pure Python (Linux, macOS, Windows, Android)
  scripts/daily_sync.sh       shell wrapper around daily.py for cron and systemd
  scripts/android_setup.sh    one-command setup in Termux: timer, dashboard service, shortcuts
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
