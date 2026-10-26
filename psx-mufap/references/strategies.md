# Strategies

All single-instrument strategies are long-or-flat: fully invested or fully in cash. A signal
is evaluated on day t's close and filled at day t+1's open (for fund NAVs, open = NAV).

| Strategy | In | Out | Parameters (defaults) | `--optimize` grid |
|---|---|---|---|---|
| `buyhold` | day 1 | never | none | none |
| `sma` | fast SMA above slow SMA | fast below slow | `--fast 50 --slow 200` | fast 10/20/50 x slow 50/100/150/200 |
| `breakout` | close above the highest close of the last `entry` days | close below the lowest close of the last `exit` days | `--entry 20 --exit 10` | entry 20/55/100 x exit 10/20/50 |
| `rsi` | RSI below `buy_below` | RSI above `sell_above` | `--period 14 --buy-below 30 --sell-above 55` | period 7/14 x buy 25/30/35 x sell 50/55/65 |
| `momentum` | every `rebalance` sessions, the top `hold` symbols by `lookback`-session return, equal weight | dropped from the top, or its return turns negative (slot goes to cash) | `--lookback 126 --hold 3 --rebalance 21` | none |

## Metrics

- **Return / CAGR**: on the equity curve, after costs. A year is 245 PSX sessions.
- **Max DD**: worst fall from a previous peak of the equity curve.
- **Sharpe**: (CAGR minus `risk_free_annual`) / annualised volatility of daily returns.
- **Trades**: number of entries. **Win**: share of closed (or still-open, marked at the last
  close) trades that made money. **In mkt**: share of days holding a position.

## Optimisation

`--optimize` tries every combination in the grid on the first 70% of the history, keeps the
one with the best Sharpe, then runs it, untouched, on the last 30%. Indicators are computed
on the full series so they are warmed up at the split, but only the last 30% counts. Small
grids on purpose: the more combinations you try, the more likely the winner is luck.

## Known limits

- No dividends in PSX price data (understates buy-and-hold of payers; overstates nothing).
- No high/low prices in the PSX end-of-day feed, so no intraday stops.
- Corporate actions (bonus shares, rights, splits) show up as price jumps. Check suspicious
  one-day moves of -30% or worse before trusting a result on that stock.
- Survivorship: the watchlist is today's names. Stocks that were delisted are not in it.
