# PSX & MUFAP skill for Claude

Find out which Pakistan Stock Exchange shares and which Pakistani mutual funds are doing
well, test trading ideas on real history, and practise with a pretend PKR account. Works in
Claude on your phone, on the web, in Claude Code, or straight from a terminal.

- **Rank** PSX stocks by 1W to 1Y returns, volatility, drawdown, Sharpe, trend and their
  3-month lead or lag on the KSE-100. Rank MUFAP funds inside each category (money market,
  income, equity, Shariah, ...), never across categories with different return conventions.
- **Backtest** moving-average, breakout, RSI and momentum-rotation strategies with next-day
  fills, trading costs, cash yield and a tune-then-test-out-of-sample mode.
- **Paper trade** shares and funds. Signals from a strategy turn into proposed orders that are
  only booked after you say yes. Nothing here can place a real order.

Python 3.8+, standard library only. Nothing to install.

## Install

**Claude app (phone, web, desktop):** zip the `psx-mufap` folder and add it as a custom skill
in Claude's settings, or download `psx-mufap.zip` from this repo's releases. Then ask, for
example: *"Which PSX stocks in my watchlist are doing best this quarter?"* or *"Top 5 Shariah
equity funds by 90-day return"*.

**Claude Code:**

```bash
git clone https://github.com/salmankhwaja/Day-Trader-PSX.git
cp -r Day-Trader-PSX/psx-mufap ~/.claude/skills/
```

or as a plugin: `/plugin marketplace add salmankhwaja/Day-Trader-PSX` then
`/plugin install psx-mufap@pk-market-skill`.

**Terminal:**

```bash
cd psx-mufap
python3 scripts/pkdata.py psx --watchlist && python3 scripts/pkdata.py mufap
python3 scripts/rank.py stocks
python3 scripts/rank.py funds --category "Money Market"
python3 scripts/backtest.py compare OGDC
python3 scripts/paper.py init && python3 scripts/paper.py status
```

## Using it from your phone

The phone app runs the scripts in a sandbox that blocks most websites. The skill handles this:

1. Claude tries a direct download first.
2. If that is blocked, it fetches the page with its web tools and imports the saved copy
   (`--from-file`). This works for the MUFAP table.
3. PSX prices may stay unreachable from the sandbox. For those, run
   `psx-mufap/scripts/daily_sync.sh` on your computer every weekday (cron line inside the
   script). It downloads prices and the MUFAP table into a folder that is its own **private**
   GitHub repo and pushes it, so Claude on your phone reads fresh data from there. The same
   daily run builds the fund NAV history that fund backtests need.

The paper account is one file, `paper/portfolio.json`, in that same data folder. Keep it in
the private data repo so every session, on any device, continues the same account.

## Repo layout

```
psx-mufap/              the skill (this is what you install)
  SKILL.md              instructions Claude follows
  scripts/pkdata.py     download / import PSX prices and MUFAP data
  scripts/rank.py       rank stocks and funds
  scripts/backtest.py   strategies, metrics, out-of-sample checks
  scripts/paper.py      paper-trading account and strategy signals
  scripts/daily_sync.sh daily refresh for your computer (cron)
  references/           strategy and data-source notes
tests/                  offline tests with synthetic PSX prices and a MUFAP sample
.claude-plugin/         Claude Code plugin manifest
```

Run the tests with `python3 -m unittest discover tests`.

## Data and terms

- PSX: end-of-day prices from the PSX Data Portal (`dps.psx.com.pk`). PSX prohibits
  redistribution or commercial use of its market data without a licence. Use it for your own
  analysis and keep downloaded prices out of public repos (`.gitignore` here excludes
  `pkmarket/`). The test fixtures are synthetic, not PSX data.
- MUFAP: the daily NAV and returns summary from `mufap.com.pk`.

Details: `psx-mufap/references/data-sources.md`.

## Disclaimer

Research and education only, not investment advice. Backtests describe the past, after
simplifying assumptions (no dividends, estimated costs); they do not predict returns.

MIT licence.
