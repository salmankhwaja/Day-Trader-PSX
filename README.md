# Day-Trader-PSX

**Ask your AI about the Pakistan Stock Exchange the way you'd ask a friend who keeps very good
spreadsheets.** Twelve skills for Claude (Gemini and ChatGPT too) that rank PSX shares and MUFAP
funds, read company news, keep your real portfolio GREEN or RED, and plan a trade from scan to
ticket.

![Claude skills: 12](https://img.shields.io/badge/Claude%20skills-12-purple) ![Python 3.8+, no dependencies](https://img.shields.io/badge/python-3.8%2B%2C%20no%20dependencies-blue) ![Licence: MIT](https://img.shields.io/badge/licence-MIT-lightgrey) ![Orders placed: 0](https://img.shields.io/badge/real%20orders%20placed-0%2C%20on%20purpose-orange)

```text
(an illustrative chat)
You:     I bought 500 OGDC at 298 through AKD this morning, stop at 280.
Claude:  Recorded: 500 OGDC @ 298.00, AKD charges Rs 223.50, stop 280. Here's your new backup.
You:     How's my portfolio?
Claude:  OGDC  GREEN  +4.1% after charges   ·   LUCK  RED  -2.3%, 1.8% above its stop   ·  …
You:     Anything setting up for tomorrow? Any news on my shares?
```

> [!CAUTION]
> **Research and practice, not investment advice.** The suggestions are rules applied to past
> prices. Nothing here can place an order, and that is deliberate: you type every ticket into your
> own broker's app.

**Contents:** [What you can ask](#what-you-can-ask) · [Your data stays with you](#your-data-stays-with-you) ·
[Start with Claude in 5 minutes](#start-with-claude-in-5-minutes) · [Claude commands, in detail](#claude-commands-in-detail) ·
[Gemini, ChatGPT and Codex](#gemini-chatgpt-and-codex) · [On your computer](#on-your-computer) ·
[On your phone](#on-your-phone) · [The dashboard on GitHub Pages](#the-dashboard-on-github-pages) · [Good to know](#good-to-know)

---

## What you can ask

| Skill | Ask it… |
|---|---|
| **`psx-mufap`**, the main one | *"Rank my watchlist"* · *"Best Shariah cement shares"* · *"Which money market fund?"* · *"I sold 200 OGDC at 315"* · *"Green or red?"* · *"What should I sell, hold or buy?"* · *"Should I buy MEBL at 250?"* · *"25,000 a month for 10 years?"* |
| `psx-scanner` | *"What's setting up today?"* · *"Any opening-range breakouts?"* · *"Top movers"* |
| `psx-news` | *"Any news on my shares?"* · *"Board meetings coming up?"* |
| `psx-analyst` | *"How were OGDC's results?"* · *"Compare MARI and PPL's earnings"* |
| `psx-insiders` | *"Are directors buying HUBC?"* |
| `psx-entry` | *"Has LUCK triggered?"* · *"Tell me when OGDC closes above 305"* |
| `psx-exit` | *"Plan a day trade in OGDC with a 2R target"* |
| `psx-timemachine` | *"What are the odds? Replay it 10,000 times"* |
| `psx-budget` | *"How many shares for a 2,500 rupee max loss?"* |
| `psx-risk` | *"Can I take this trade?"* (PASS or BLOCK, with reasons) |
| `psx-broker` | *"Give me the tickets for my app"* · *"E1 filled at 301.60"* |
| `psx-alerts` | *"Alert me if OGDC goes above 310"* · *"Ring at my stop and target"* |

Start with **`psx-mufap`** alone: it does the market, funds, portfolio and advice. The other
eleven are a day-trading desk you add when you want to plan trades by the day or the week. Every
skill counts PSX realities in: the two Friday sessions, the 10% (or Rs 1) price limits, broker
commission, sales tax, CDC and exchange levies, in rupees.

## Your data stays with you

> [!IMPORTANT]
> **This repo is code only. It holds no market data and no portfolio, and nothing is sent to us:
> there is no "us" server.** Your prices, trades, brokers and settings live in one folder,
> `pkmarket`, on **your** computer or phone, or inside **your own** logged-in AI chat. You carry
> it between chats and devices as **one backup zip** that only you keep.

- In a chat app, attach your latest `pkmarket-backup-….zip` when you start; Claude restores it,
  and hands you a fresh one after you record anything. Keep the newest one (Files on iPhone,
  Downloads on Android).
- Prices come straight from the PSX data portal and MUFAP to wherever the skill runs. PSX doesn't
  allow its data to be republished, so keep your backup private.
- No broker passwords are ever asked for or stored.

---

## Start with Claude in 5 minutes

The least friction: no installs, works on the web, the desktop app, iPhone and Android.

1. **Download the skills:** [`psx-mufap.zip`](https://github.com/salmankhwaja/Day-Trader-PSX/raw/main/zips/psx-mufap.zip)
   and, if you want the desk, any of the [other eleven](https://github.com/salmankhwaja/Day-Trader-PSX/tree/main/zips) (all in the `zips` folder; on a phone, open the file and tap Download).
2. **Turn on code execution** in Claude's settings (skills need it; Free, Pro, Max, Team and
   Enterprise plans all have skills).
3. **Add them:** on claude.ai or the desktop app, open **Customize › Skills**, upload each zip and
   switch it on. Skills belong to your account, so your phone has them too.
4. **Ask:** *"Set me up: my broker is AKD, my watchlist is OGDC, PPL, MARI, HUBC, LUCK and MEBL,
   and ask me the risk questions."* Then keep the backup zip Claude gives you.

> [!TIP]
> Claude's chat sandbox usually can't reach the PSX price server, so news, results and MUFAP come
> in through Claude's web fetch, and daily price history comes in your backup zip. Make that zip on
> a [computer](#on-your-computer) or [Android phone](#on-your-phone) that runs the morning update,
> or ask in Claude Code, which downloads everything itself. (Team and Enterprise owners can allow
> `dps.psx.com.pk` and `www.mufap.com.pk` under Admin settings › Capabilities.)

---

## Claude commands, in detail

### How to call a skill

| Where | How | Example |
|---|---|---|
| **Claude app** (web, desktop, iPhone, Android) | Just ask: Claude picks the skill from what you say. Name it to be sure | *"Use psx-news: anything on OGDC this week?"* |
| **Claude Code** (terminal, or the desktop app's Code tab) | `/` + skill name + your request, or just ask | `/psx-mufap what should I sell today?` |
| Claude Code, installed as a plugin | `/psx-mufap:` + the skill | `/psx-mufap:psx-scanner breakouts this morning` |

The twelve slash commands in Claude Code:

| Command | Does | Try |
|---|---|---|
| `/psx-mufap` | prices, rankings, funds, your portfolio, advice, risk, SIP, dashboard | `/psx-mufap how is my portfolio doing?` |
| `/psx-scanner` | daily setups, opening-range breakouts, movers | `/psx-scanner scan the whole market` |
| `/psx-news` | announcements with PDFs, upcoming board meetings and book closures | `/psx-news my holdings, last 30 days` |
| `/psx-analyst` | latest quarter and year, growth, margins, P/E, payout | `/psx-analyst OGDC vs PPL` |
| `/psx-insiders` | directors' and sponsors' dealings | `/psx-insiders anything new?` |
| `/psx-entry` | waiting, triggered or expired | `/psx-entry has LUCK triggered?` |
| `/psx-exit` | stop, target, flat-by time, reward-to-risk after charges | `/psx-exit day trade OGDC, stop at the range middle` |
| `/psx-timemachine` | thousands of replays from the share's own past | `/psx-timemachine what are the odds?` |
| `/psx-budget` | the size and the bracket: buy, stop-loss, take-profit | `/psx-budget max loss 2,500` |
| `/psx-risk` | PASS or BLOCK per order | `/psx-risk check my orders` |
| `/psx-broker` | tickets to type, fills, today, flatten | `/psx-broker E1 filled at 301.60` |
| `/psx-alerts` | price, move, stop, target and clock alerts | `/psx-alerts ring the bells` |

> [!TIP]
> Claude always asks **which prices to use** (the last download, a fresh one, or live) and says
> which it used; **reads every trade back** before recording it; and in a chat app, gives you the
> new backup zip. Ask in English, Urdu or Roman Urdu.

### Market and funds

| Say | You get |
|---|---|
| *"Get today's prices for my watchlist"* · *"Download the whole market"* | daily prices, KSE-100, Shariah flags, company pages |
| *"Live prices for my holdings"* · *"What's OGDC at right now?"* | the PSX market watch, during market hours |
| *"Show my watchlist"* · *"Add LUCK and DGKC"* · *"Add the top 5 Shariah cement shares"* | your list, with sector, Shariah, last price and 1-month move |
| *"Rank my watchlist"* · *"Top 20 in the whole market"* · *"Highest dividend yields"* | ranked on returns, Sharpe, trend, vs the KSE-100, dividends |
| *"Which sectors are leading?"* · *"Compare LUCK, DGKC and MLCF"* | sector table; side by side |
| *"How did a moving-average strategy do on OGDC?"* | backtests with costs and an out-of-sample test |
| *"Which funds for low risk?"* · *"Shariah equity funds"* · *"How are my funds doing?"* | MUFAP funds ranked inside their category; HOLD or REVIEW for yours |

### Your portfolio

| Say | You get |
|---|---|
| *"My broker is AKD"* · *"I use Finqalab"* · *"0.12% or 3 paisa a share, Sindh tax"* | the broker and its charges (presets or your own) |
| *"I bought 500 OGDC at 298 at 10:42, stop 280, commission 223.50"* | the buy, with your time, stop and contract-note charges |
| *"Sold 200 OGDC at 315"* · *"Sold all my OGDC at 320"* | the sale, matched to your oldest shares |
| *"Move my OGDC stop to 285"* · *"Back to the automatic stop"* | your own stop, or the trailing one |
| *"I put 200,000 in Alfalah Cash Fund at 106.73"* · *"Redeem all of it"* | fund buys and redemptions |
| *"Any dividends due?"* · *"I received 3,825 from OGDC"* · *"I deposited 500,000"* | dividends and cash |
| *"Green or red?"* · *"Each purchase separately"* · *"At live prices"* | every holding against what you paid, after charges |
| *"Realised profit this year?"* · *"What have my brokers cost me?"* | P/L per sale; charges by broker |
| *"Import my trades"* (attach a CSV) · *"Show my trades"* · *"Delete entry 7"* | bulk in, the ledger, corrections |

### What to do next

| Say | You get |
|---|---|
| *"What should I sell, hold or buy?"* | SELL / TRIM / REVIEW / HOLD with stops, and buy ideas sized to your cash |
| *"Should I buy MEBL at 250, stop 232?"* | a verdict with backtest, target, size, and rupees at the stop and the target |
| *"Give me the order tickets"* | stop-losses, buys, trims and take-profits to type into your app |
| *"Ask me the risk questions"* · *"Make me aggressive"* · *"No more than 6 shares"* | your risk style and every setting it drives |
| *"How many shares at 300 with a stop at 282?"* · *"How much am I risking?"* | position size; money at risk, VaR, beta, concentration |
| *"25,000 a month for 10 years, up 10% a year?"* · *"How much to reach 50 lakh in 8 years?"* | SIP projection; the monthly amount for a goal |
| *"Start a paper account with 10 lakh"* · *"Propose a paper portfolio"* | practice money |
| *"Show the dashboard"* · *"Give me my backup"* | the one-file dashboard; your zip |

### A day trade, start to finish

```text
/psx-scanner any opening-range breakouts?        → LUCK broke its 15-minute range at 09:50
/psx-news LUCK                                   → no surprises today
/psx-exit plan LUCK, stop at the range middle    → stop 842, target 2R 873, flat by 15:20
/psx-timemachine what are the odds?              → past ORBs in LUCK: target first 41%, stop first 37%
/psx-budget max loss 2,500                       → 160 shares, bracket E1 / E1-SL / E1-TP
/psx-risk check                                  → PASS
/psx-broker give me the tickets                  → type them into your app
/psx-broker E1 filled at 852.10                  → recorded in your portfolio; /psx-alerts can ring at the stop
```

(Illustrative numbers.) A chat can't run timers or ring while you're away: for the morning update
and alerts, run it on a [computer](#on-your-computer) or [Android phone](#on-your-phone).
Every command behind every sentence is in the [command reference](docs/REFERENCE.md#command-cheat-sheet).

---

## Gemini, ChatGPT and Codex

The skills are plain `SKILL.md` folders, so other assistants read them too. They're written and
tested with Claude; others may follow them a little differently.

| Assistant | Add the skills | Call them |
|---|---|---|
| **Gemini app** | upload the `psx-mufap` folder (with `SKILL.md` at the top) as a Skill | type `/psx-mufap`, or just ask |
| **Gemini CLI** | `cp -r Day-Trader-PSX/psx-* ~/.agents/skills/` | just ask; `/skills list` |
| **ChatGPT** Business, Enterprise, Edu | sidebar › Plugins › Skills › Create › Upload from your computer | name the skill, or just ask |
| **Codex** (works with ChatGPT Plus) | `cp -r Day-Trader-PSX/psx-* ~/.agents/skills/` | `$psx-mufap record a buy of 500 OGDC at 298` |

The same things to say work everywhere. Gemini's and ChatGPT's app sandboxes can't reach
websites, so carry your backup zip there too; the CLIs run on your computer and download
everything.

---

## On your computer

For the full thing: downloads straight from PSX, files that stay put, a morning update at 07:00,
alerts that ring, and a dashboard. Linux, macOS or Windows.

```bash
git clone https://github.com/salmankhwaja/Day-Trader-PSX.git && cd Day-Trader-PSX
python3 psx-mufap/scripts/pkdata.py init                       # your data folder: ~/pkmarket
python3 psx-mufap/scripts/watchlist.py set OGDC PPL MARI HUBC LUCK MEBL --fetch
(cd psx-mufap/scripts && ./install_services.sh)                # 07:00 update + dashboard
```

**Windows, in Command Prompt:** install [Python 3](https://www.python.org/downloads/) (tick *Add
python.exe to PATH*), then:

```bat
cd Day-Trader-PSX\psx-mufap\scripts
install_windows.bat                                            &rem data folder + 07:00 weekday update
py watchlist.py set OGDC PPL MARI HUBC LUCK MEBL --fetch
py pkm.py                                                      &rem the menu
```

Then pick how to talk to it:

- **Claude Code:** `cp -r psx-* ~/.claude/skills/` (Windows: `for /d %d in (psx-*) do xcopy /E /I /Y %d "%USERPROFILE%\.claude\skills\%d"`), run `claude`, and ask. Or install as a plugin
  from inside Claude Code: `/plugin marketplace add salmankhwaja/Day-Trader-PSX`, then
  `/plugin install psx-mufap@pk-market-skill`.
- **Gemini CLI or Codex:** copy to `~/.agents/skills/` (table above).
- **No AI at all:** `python3 psx-mufap/scripts/pkm.py`, a numbered menu.

`python3 psx-mufap/scripts/pkdata.py backup` makes the zip you carry into chat apps. Python 3.8+,
standard library only: nothing to `pip install`.

## On your phone

| Phone | What works | How |
|---|---|---|
| **iPhone or iPad** | ask anything, look at your dashboard | the Claude app (skills come with your account) and your backup zip in Files; open your computer's dashboard over Tailscale, or the one-file `dashboard.html` |
| **Android, chat only** | the same as iPhone | the Claude app and your backup zip in Downloads |
| **Android, the whole thing** | everything a computer does, no computer needed | Termux from F-Droid, about 20 minutes: [Android guide](docs/REFERENCE.md#run-it-on-your-android-phone) |
| **Any phone, in the browser** | everything: prices fetched for you, holdings added on the page, advice, backups | [GitHub Pages](#the-dashboard-on-github-pages): no Termux, no computer |

On Android with Termux the morning update, alerts and the dashboard run on the phone itself, and
home-screen buttons do the common jobs. Advice and holdings print as short cards, one per share,
instead of tables that wrap off the screen (`--view table` if you miss them).

---

## The dashboard on GitHub Pages

The whole thing in a browser, no Termux and no computer needed: a GitHub Action fetches PSX and
MUFAP prices for you, and you add your holdings on the website. Live copy:
**https://salmankhwaja.github.io/Day-Trader-PSX/**

> [!NOTE]
> **The page is public; your numbers are not.** Prices are published only *encrypted* (PSX
> doesn't allow its data to be republished) and unlock with your passphrase on your device.
> Your holdings live **only in this browser on this device** (IndexedDB): never uploaded, not to
> GitHub, not to anyone. Move them between devices with **Data › Save backup** (encrypted) and
> **Restore**.

**Set it up once** (for this repo or your fork):

1. **A passphrase:** *Settings › Secrets and variables › Actions › New repository secret*, name
   `PSX_DATA_KEY`, value: a long passphrase you'll remember. It encrypts the prices.
2. **The price workflow** is already on (`.github/workflows/feed.yml`); in a fork, enable Actions
   when GitHub asks. Until the secret exists it fetches nothing.
3. **Pages:** *Settings › Pages › Deploy from a branch › `main` / `/ (root)` › Save.*
4. **First fill:** *Actions › feed › Run workflow*, mode **backfill** (about 20 minutes: a year of
   history for every share). After that it runs by itself.
5. Open the page, enter the passphrase, then **My portfolio › Start: pick your broker**, and add
   your buys and sells, funds and cash.

**Prices:** every weekday at 12:15, after the close at 16:45, and MUFAP NAVs at 22:45 (and
Saturday). **Refresh prices now** (top of the page, or Data) opens the workflow on GitHub: tap
*Run workflow* and the new prices land in 1-3 minutes. No token is kept on the site. Cost: nothing
(standard runners are free on public repos); each run takes 1-3 minutes and commits only when a
price changed.

**Your holdings, in and out:** Data saves an encrypted backup, restores one, imports a trades CSV
or the `ledger.json` from the Python tools, and exports both. Same format both ways, so Termux,
your computer and the website can share one portfolio.

**PK Wealth too:** [PK Wealth](https://github.com/salmankhwaja/WealthTracker) on the same Pages
site reads this feed's `feed/latest.enc.json`, so PSX prices are fetched once for both apps,
unlocked by the same passphrase.

**Just looking?** Tap *Try the sample data*: a made-up market, sample funds and a sample portfolio,
with a banner saying so. **Exit sample** goes back; your own data is never touched.

**The Python way still works.** Termux and the computer tools are unchanged: build `data.json`
(`python3 psx-mufap/scripts/dashboard.py build`) and **Load data file**, or run
`dashboard.py serve` for live prices ([how](docs/REFERENCE.md#step-7-open-your-dashboard)).

---

## Good to know

- **Where the data comes from:** the PSX data portal (daily and intraday prices, company pages,
  announcements, financials, market watch) and MUFAP (fund NAVs and returns). A second opinion
  from PakistaniBulls is opt-in, from a page you saved, for personal use.
- **Honest limits:** end-of-day data is reliable; intraday needs the portal to be reachable;
  backtests describe the past; tight day trades often fail after PSX charges, and the tools say so
  in rupees. Most people who day trade lose money.
- **The full manual:** [docs/REFERENCE.md](docs/REFERENCE.md) has every command, setting, broker
  preset, the schedule, the dashboard, troubleshooting, FAQ and how the suggestions work.
- **Credits:** the desk's design is adapted from [Jake Schincariol's day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
  (US markets), rebuilt for PSX.
- **Contributing:** issues and pull requests welcome; see [CLAUDE.md](CLAUDE.md) for the rules
  (tests pass, docs updated, no market data in the repo).
- **Licence:** [MIT](LICENSE). By [Khwaja Muhammad Salman](https://github.com/salmankhwaja).
