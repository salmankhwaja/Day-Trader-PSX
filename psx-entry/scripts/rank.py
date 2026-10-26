#!/usr/bin/env python3
"""Rank PSX stocks and MUFAP funds by recent performance.

  rank.py stocks [--top 10] [--symbols A B ...] [--sort score|1m|3m|6m|1y|ytd|sharpe|div_yield] [--json]
  rank.py stocks --all [--sector cement] [--shariah]   every listed share, not just the watchlist
  rank.py sectors [--shariah]                           sector league table (median returns)
  rank.py funds  [--top 5] [--category "Equity"] [--sort score|ytd|d30|d90|d365|y3] [--json]
  rank.py categories        one line per MUFAP category: fund count, median and best returns

Stocks use the price files from `pkdata.py psx`. For each symbol:
  returns over 1W, 1M, 3M, 6M, 1Y (5/21/63/126/245 sessions) and year to date,
  annualised volatility and max drawdown over the last year,
  Sharpe = (1Y return - risk-free) / 1Y volatility,
  trend: last close vs its 50- and 200-day averages,
  vs index: 3M return minus the benchmark's (KSE100 by default).
  score = weighted average percentile (0-100) of 1M, 3M, 6M, 1Y returns and Sharpe across the
  list; the weights are "score_weights" in your risk profile (momentum-heavy when aggressive,
  Sharpe-heavy when conservative).

Funds use the newest MUFAP snapshot from `pkdata.py mufap`. Funds are only compared
inside their own category. Money market, income and fixed-rate categories report
ANNUALISED returns; equity, balanced and asset-allocation categories report ABSOLUTE
returns, so never compare numbers across those two groups.
  score = average percentile within the category of the 30-day, 90-day and 1-year
  returns; a fund needs at least two of the three, so one good week is not enough.

Past performance is not a forecast. This is research, not investment advice.
"""
import argparse
import csv
import datetime as dt
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import freshness as F  # noqa: E402
from pkdata import latest_mufap, MUFAP_PERIODS  # noqa: E402
import psxinfo as P  # noqa: E402

PERIODS = [("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", C.TRADING_DAYS)]


def percentiles(values):
    """Percentile rank 0..100 for each value (None stays None). Ties share the average rank."""
    pts = sorted(v for v in values if v is not None)
    n = len(pts)
    out = []
    for v in values:
        if v is None or n == 0:
            out.append(None)
        elif n == 1:
            out.append(50.0)
        else:
            below = sum(1 for p in pts if p < v)
            equal = sum(1 for p in pts if p == v)
            out.append(100.0 * (below + (equal - 1) / 2.0) / (n - 1))
    return out


def stock_metrics(rows, rf=0.0):
    closes = [r["close"] for r in rows]
    last = len(closes) - 1
    m = {"last_date": rows[-1]["date"], "close": closes[-1], "days": len(closes)}
    for name, n in PERIODS:
        m[name] = C.pct(closes[-1], closes[last - n]) if last - n >= 0 else None
    year = rows[-1]["date"][:4]
    prior = [r["close"] for r in rows if r["date"][:4] < year]
    m["ytd"] = C.pct(closes[-1], prior[-1]) if prior else None
    window = closes[-(C.TRADING_DAYS + 1):]
    m["vol"] = C.ann_vol(C.daily_returns(window))
    m["mdd"] = C.max_drawdown(window)
    m["sharpe"] = ((m["1y"] - rf) / m["vol"]) if m["1y"] is not None and m["vol"] else None
    s50, s200 = C.sma(closes, 50, last), C.sma(closes, 200, last)
    m["above_50"] = closes[-1] > s50 if s50 else None
    m["above_200"] = closes[-1] > s200 if s200 else None
    vols = [r["volume"] for r in rows[-60:]]
    m["avg_volume"] = sum(vols) / len(vols) if vols else 0
    return m


def trend_label(m):
    a, b = m["above_50"], m["above_200"]
    if a is None or b is None:
        return "?"
    return {(True, True): "up", (False, False): "down"}.get((a, b), "mixed")


def stock_info(h, cfg, symbol, uni=None, payouts=None, price=None):
    """Name, sector, Shariah flag and dividend summary for one symbol (whatever is on file)."""
    uni = uni if uni is not None else P.load_universe(h)
    u = uni.get(symbol, {})
    c = P.load_company(h, symbol)
    info = {"name": (c or {}).get("name") or u.get("name"), "sector": (c or {}).get("sector"),
            "shariah": u.get("shariah") if u else None, "pe": (c or {}).get("pe"),
            "mcap_m": (c or {}).get("mcap_m") or u.get("mcap_m"), "tags": u.get("tags") or (c or {}).get("tags") or []}
    if c or payouts:
        info["dividends"] = P.dividend_summary(cfg, symbol, c, payouts or [], price=price)
    else:
        info["dividends"] = None
    return info


def select_symbols(h, cfg, symbols=None, all_=False):
    if symbols:
        return [s.upper() for s in symbols]
    if all_:
        uni = P.load_universe(h)
        if not uni:
            sys.exit("no universe.json yet: run `pkdata.py universe` (then `pkdata.py psx --all`)")
        return sorted(uni)
    return [s.upper() for s in cfg["watchlist"]]


def rank_stocks(h, cfg, symbols=None, sort="score", all_=False, sector=None, shariah=False,
                min_volume=None, info=True):
    """Rank symbols. With all_, every share in universe.json that has prices, after a liquidity
    filter (average daily volume over 60 sessions >= min_volume, default config min_avg_volume)."""
    symbols = select_symbols(h, cfg, symbols, all_)
    if min_volume is None:
        min_volume = cfg.get("min_avg_volume", 50000) if all_ else 0
    bench = cfg["benchmark"].upper()
    bm = None
    if os.path.exists(C.price_path(h, bench)):
        brows = C.read_prices(C.price_path(h, bench))
        if len(brows) > 70:
            bm = stock_metrics(brows, cfg["risk_free_annual"])
    uni = P.load_universe(h)
    payouts = P.load_payouts(h)
    res, missing, illiquid = [], [], 0
    for s in symbols:
        if s == bench:
            continue
        p = C.price_path(h, s)
        if not os.path.exists(p):
            missing.append(s)
            continue
        rows = C.read_prices(p)
        if len(rows) < 30:
            missing.append(s)
            continue
        m = stock_metrics(rows, cfg["risk_free_annual"])
        if m["avg_volume"] < min_volume:
            illiquid += 1
            continue
        m["symbol"] = s
        m["vs_index_3m"] = (m["3m"] - bm["3m"]) if bm and m["3m"] is not None and bm["3m"] is not None else None
        if info:
            m.update(stock_info(h, cfg, s, uni, payouts, m["close"]))
            d = m.get("dividends") or {}
            m["div_yield"] = d.get("yield_ttm")
        if sector and sector.lower() not in (m.get("sector") or "").lower():
            continue
        if shariah and not m.get("shariah"):
            continue
        res.append(m)
    weights = cfg.get("score_weights") or {"1m": 1, "3m": 1, "6m": 1, "1y": 1, "sharpe": 1}
    keys = [k for k in ("1m", "3m", "6m", "1y", "sharpe") if float(weights.get(k, 0)) > 0]
    pcts = {k: percentiles([m[k] for m in res]) for k in keys}
    for i, m in enumerate(res):
        got = [(pcts[k][i], float(weights[k])) for k in keys if pcts[k][i] is not None]
        tw = sum(w for _, w in got)
        m["score"] = sum(p * w for p, w in got) / tw if tw else None
    res.sort(key=lambda m: (m.get(sort) is None, -(m.get(sort) or 0)))
    return res, bm, {"missing": missing, "illiquid": illiquid, "min_volume": min_volume}


def sector_summary(res):
    """Per-sector median returns from ranked stock metrics."""
    by = {}
    for m in res:
        by.setdefault(m.get("sector") or "UNKNOWN", []).append(m)
    out = []
    for sec, ms in by.items():
        def med(k):
            v = [x[k] for x in ms if x.get(k) is not None]
            return statistics.median(v) if v else None
        best = max(ms, key=lambda x: x.get("score") or -1)
        out.append({"sector": sec, "count": len(ms), "1m": med("1m"), "3m": med("3m"), "1y": med("1y"),
                    "div_yield": med("div_yield"), "best": best["symbol"],
                    "shariah": sum(1 for x in ms if x.get("shariah"))})
    out.sort(key=lambda r: (r["3m"] is None, -(r["3m"] or 0)))
    return out


def fund_rows(h):
    snap = latest_mufap(h)
    if not snap:
        sys.exit("no MUFAP data yet: run pkdata.py mufap first")
    out = []
    with open(snap, newline="") as f:
        for r in csv.DictReader(f):
            for k in ["nav"] + MUFAP_PERIODS:
                r[k] = float(r[k]) if r[k] not in ("", None) else None
            out.append(r)
    return os.path.basename(snap)[:-4], out


def rank_funds(funds, category=None, sort="score"):
    by_cat = {}
    for f in funds:
        if category and category.lower() not in f["category"].lower():
            continue
        by_cat.setdefault(f["category"], []).append(f)
    for cat, fs in by_cat.items():
        keys = ["d30", "d90", "d365"]
        pcts = {k: percentiles([f[k] for f in fs]) for k in keys}
        for i, f in enumerate(fs):
            got = [pcts[k][i] for k in keys if pcts[k][i] is not None]
            # Two of the three periods at least, so a brand-new fund can't top the list on one number.
            f["score"] = sum(got) / len(got) if len(got) >= 2 else None
        fs.sort(key=lambda f: (f.get(sort) is None, -(f.get(sort) or 0)))
    return by_cat


def p1(x):
    return "n/a" if x is None else "%.1f" % x


def cmd_stocks(a, h, cfg):
    F.decide(a, h, cfg, F.scope(h, cfg, a.symbols, a.all, held=False), payouts=True)
    res, bm, notes = rank_stocks(h, cfg, a.symbols, a.sort, a.all, a.sector, a.shariah, a.min_volume)
    if a.json:
        print(json.dumps({"stocks": res, "benchmark": bm, "notes": notes}, indent=1, default=str))
        return 0
    if not res:
        sys.exit("no stocks to rank: download prices first (pkdata.py psx --watchlist, or universe + psx --all)")
    scope = "all PSX" if a.all else ("chosen symbols" if a.symbols else "watchlist")
    extra = "".join([", sector ~ %r" % a.sector if a.sector else "", ", Shariah only" if a.shariah else ""])
    print("PSX ranking (%s%s), %d stocks, prices to %s, sorted by %s" % (
        scope, extra, len(res), max(m["last_date"] for m in res), a.sort))
    if bm:
        print("%s: 1M %s  3M %s  1Y %s  YTD %s" % (cfg["benchmark"], C.fmt_pct(bm["1m"]), C.fmt_pct(bm["3m"]),
                                                  C.fmt_pct(bm["1y"]), C.fmt_pct(bm["ytd"])))
    rows = []
    for i, m in enumerate(res[:a.top], 1):
        rows.append([i, m["symbol"] + (" ☪" if m.get("shariah") else ""), (m.get("sector") or "")[:18],
                     "%.2f" % m["close"], C.fmt_pct(m["1m"]), C.fmt_pct(m["3m"]), C.fmt_pct(m["1y"]),
                     C.fmt_pct(m["vs_index_3m"]), "n/a" if m["sharpe"] is None else "%.2f" % m["sharpe"],
                     C.fmt_pct(m.get("div_yield")), trend_label(m), p1(m["score"])])
    print(C.md_table(["#", "Symbol", "Sector", "Close", "1M", "3M", "1Y", "3M vs idx", "Sharpe", "Div yld",
                      "Trend", "Score"], rows))
    print("☪ = in the KMI All Share (Shariah-compliant) index. Div yld = last 12 months' cash "
          "dividends / price, assuming Rs 10 face value unless config says otherwise.")
    if notes["illiquid"]:
        print("left out %d illiquid shares (60-day average volume under %s)" % (notes["illiquid"],
                                                                                "{:,.0f}".format(notes["min_volume"])))
    if notes["missing"] and len(notes["missing"]) <= 30:
        print("no price data for: %s" % " ".join(notes["missing"]))
    elif notes["missing"]:
        print("no price data for %d symbols" % len(notes["missing"]))
    return 0


def cmd_sectors(a, h, cfg):
    res, bm, notes = rank_stocks(h, cfg, None, "score", True, None, a.shariah, a.min_volume)
    if not res:
        sys.exit("needs universe + prices + company pages: pkdata.py universe; psx --all; company --all")
    rows = [[r["sector"][:28], r["count"], r["shariah"], C.fmt_pct(r["1m"]), C.fmt_pct(r["3m"]),
             C.fmt_pct(r["1y"]), C.fmt_pct(r["div_yield"]), r["best"]] for r in sector_summary(res)]
    print("PSX sectors, median returns of liquid shares%s" % (" (Shariah only)" if a.shariah else ""))
    print(C.md_table(["Sector", "Stocks", "☪", "1M", "3M", "1Y", "Div yld", "Top score"], rows))
    return 0


def cmd_funds(a, h, cfg):
    F.decide(a, h, cfg, funds=True)
    date, funds = fund_rows(h)
    by_cat = rank_funds(funds, a.category, a.sort)
    if a.json:
        print(json.dumps({"report_date": date, "categories": by_cat}, indent=1, default=str))
        return 0
    if not by_cat:
        sys.exit("no category matches %r; run rank.py categories to see the names" % a.category)
    print("MUFAP ranking, report %s, sorted by %s within each category" % (date, a.sort))
    for cat in sorted(by_cat):
        fs = by_cat[cat]
        kind = fs[0]["return_type"]
        print("\n%s (%d funds, %s returns %%)" % (cat, len(fs), kind))
        rows = [[i, f["fund"], p1(f["d30"]), p1(f["d90"]), p1(f["ytd"]), p1(f["d365"]), p1(f["score"])]
                for i, f in enumerate(fs[:a.top], 1)]
        print(C.md_table(["#", "Fund", "30D", "90D", "YTD", "1Y", "Score"], rows))
        stale = [f["fund"] for f in fs[:a.top] if f["validity_date"] and
                 (dt.date.fromisoformat(date) - dt.date.fromisoformat(f["validity_date"])).days > 3]
        if stale:
            print("NAV older than 3 days: " + ", ".join(stale))
    return 0


def cmd_categories(a, h, cfg):
    date, funds = fund_rows(h)
    by_cat = {}
    for f in funds:
        by_cat.setdefault(f["category"], []).append(f)
    rows = []
    for cat in sorted(by_cat):
        fs = by_cat[cat]
        vals = [f["d365"] for f in fs if f["d365"] is not None]
        ytd = [f["ytd"] for f in fs if f["ytd"] is not None]
        rows.append([cat, fs[0]["return_type"][:4], len(fs),
                     p1(statistics.median(ytd)) if ytd else "n/a",
                     p1(statistics.median(vals)) if vals else "n/a",
                     p1(max(vals)) if vals else "n/a"])
    print("MUFAP categories, report %s (returns in %%; 'annu' = annualised, 'abso' = absolute)" % date)
    print(C.md_table(["Category", "Type", "Funds", "Median YTD", "Median 1Y", "Best 1Y"], rows))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stocks")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--symbols", nargs="*")
    p.add_argument("--all", action="store_true", help="every listed share, not just the watchlist")
    p.add_argument("--sector", help="substring of the PSX sector name, e.g. 'cement'")
    p.add_argument("--shariah", action="store_true", help="KMI All Share members only")
    p.add_argument("--min-volume", type=float, help="minimum 60-day average daily volume")
    p.add_argument("--sort", default="score",
                   choices=["score", "1w", "1m", "3m", "6m", "1y", "ytd", "sharpe", "div_yield"])
    p.add_argument("--json", action="store_true")
    F.add_args(p)
    p = sub.add_parser("sectors")
    p.add_argument("--shariah", action="store_true")
    p.add_argument("--min-volume", type=float)
    p = sub.add_parser("funds")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--category")
    p.add_argument("--sort", default="score", choices=["score"] + MUFAP_PERIODS)
    p.add_argument("--json", action="store_true")
    F.add_args(p)
    sub.add_parser("categories")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"stocks": cmd_stocks, "funds": cmd_funds, "categories": cmd_categories,
            "sectors": cmd_sectors}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
