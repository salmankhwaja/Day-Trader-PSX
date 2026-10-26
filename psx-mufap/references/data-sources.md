# Data sources

## PSX: `https://dps.psx.com.pk/timeseries/eod/<SYMBOL>`

The PSX Data Portal's end-of-day series. It is undocumented; the format below is how
open-source PSX tools describe it, and `pkdata.py` checks it on every download.

**Session key (since late 2026).** The portal returns 404 for this URL (and may for
`/indices/...` and `/payouts`) unless the request looks like its own page's: a session cookie
plus the key each portal page embeds as `window.__ps = {"_k": "..."}`, sent back in an
`X-Req-Id` header with `X-Requested-With: XMLHttpRequest` (the site's `script.js` does
`$.ajaxSetup({headers: {"X-Req-Id": __ps._k}})`). `common.http_get` reads the key from the home
page (or a company page) once per run and retries once with a fresh key on 401/403/404.

JSON:

```json
{"status": 1, "message": "", "data": [[1792697400, 245.10, 1834500, 243.00], ...]}
```

Each row is `[unix_time, close, volume, open]`, newest first, about five years deep. There is
no high/low. Index symbols such as `KSE100` are reported to work the same way; if one
fails, `rank.py` simply skips the benchmark column. `pkdata.py` converts the
timestamp to the Pakistan (UTC+5) calendar date and merges new rows into the existing CSV.

Terms: PSX prohibits dissemination or commercial use of its market data without a licence
(contact marketdatarequest@psx.com.pk). Personal analysis is the intended use here. Do not
publish the downloaded prices.

## MUFAP: `https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=1`

The Mutual Funds Association of Pakistan's daily "NAV Returns Performance Summary" for every
open-end fund. One table per category; a heading row names the category and whether its
returns are annualised or absolute. Columns:

`Sector | Fund Name | Rating | Benchmark | Validity Date | NAV | YTD | MTD | 1 Day | 15 Days |
30 Days | 90 Days | 180 Days | 270 Days | 365 Days | 2 Years | 3 Years`

Negative returns appear in brackets, `(3.13)`; missing ones as `N/A`. "Validity Date" is the
date of the NAV, which can lag the report date by a day or two (more for some funds).

Return conventions follow MUFAP's methodology: money market, income, fixed-rate and similar
fixed-income categories report annualised returns; equity and mixed categories report
absolute returns for the period. Returns are net of fees but before any sales load.

`pkdata.py mufap` saves a dated snapshot and appends each fund's NAV to
`mufap/nav_history.csv`. MUFAP's own pages do not offer a long NAV history in one request, so
fund backtests work from the history you collect (run it daily, e.g. with
`scripts/daily_sync.sh`).

## PSX company data

All from the PSX Data Portal, parsed by `scripts/psxinfo.py`:

| Page | Gives | Used for |
|---|---|---|
| `/indices/ALLSHR` | every share in the KSE All Share Index: name, price, shares, market cap | the `--all` universe |
| `/indices/KMIALLSHR` | the KMI All Share Islamic Index members (about 310) | the Shariah flag (☪) |
| `/company/<SYMBOL>` | sector, P/E (TTM), 52-week range, market cap, free float, and the payouts table: announcement date, period, details, book closure | sectors, valuation, dividend history |
| `/payouts` | the latest dividend announcements across the market | new announcements and book closures between weekly company refreshes |

Tags after a symbol on index pages are PSX's own markers (for example `XD`, trading
ex-dividend, and `NC`); they are kept as-is in `universe.json`.

Payout details read like `60% (F) (D)`: 60% of face value in cash (D), final (F); `(i)`,
`(ii)`, `(iii)` are interims; `(B)` bonus shares; `(R)` rights. Dividend per share is the percent
times face value, which the pages don't show: Rs 10 for most shares, otherwise set
`face_values` in config.json. "Expected next" is the date of last year's equivalent
announcement plus one year: an estimate, not a company notice.

KMI membership is recomposed periodically by PSX; refreshing the universe weekly picks that up.
