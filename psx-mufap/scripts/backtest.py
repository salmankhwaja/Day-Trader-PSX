#!/usr/bin/env python3
"""Backtest simple, honest strategies on PSX stocks and MUFAP fund NAVs.

  backtest.py run SYMBOL --strategy sma [--fast 50 --slow 200]
  backtest.py run SYMBOL --strategy breakout [--entry 20 --exit 10]
  backtest.py run SYMBOL --strategy rsi [--period 14 --buy-below 30 --sell-above 55]
  backtest.py run SYMBOL --strategy buyhold
  backtest.py run --fund "NBP Islamic Energy Fund" --strategy sma --fast 10 --slow 30
  backtest.py momentum [--symbols ...] [--lookback 126 --hold 3 --rebalance 21]
  backtest.py run SYMBOL --strategy sma --optimize     tune on the first 70%, test on the rest
  backtest.py compare SYMBOL                            every strategy on one symbol, side by side

Rules that keep the numbers honest
  * A signal is computed on day t's close and filled at day t+1's OPEN, never the same bar.
  * Every buy and sell pays cost_bps_per_side from config.json (default 20 bps).
  * Cash that is not invested earns risk_free_annual (default 0; set it to a money-market
    yield to see whether a strategy beats simply parking cash).
  * --optimize picks parameters on the in-sample 70% only and reports the untouched 30%
    separately. Trust the out-of-sample line, not the in-sample one.
  * Dividends are not in the PSX price series, so buy-and-hold of high-payout stocks is
    understated. Fund NAV history only covers the days you have run `pkdata.py mufap`.

Output: total return, CAGR, volatility, Sharpe, max drawdown, trades, win rate and time in
the market, next to buy-and-hold over the same days. --equity-csv FILE saves the daily curve.

Past results do not predict future ones. This is research, not investment advice.
"""
import argparse
import csv
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


# ------------------------------------------------------------------ signals
# Each returns f(i) -> 1 (be long), 0 (be flat) or None (no opinion: keep the position).

def sig_buyhold(closes, **_):
    return lambda i: 1


def sig_sma(closes, fast=50, slow=200, **_):
    def f(i):
        a, b = C.sma(closes, fast, i), C.sma(closes, slow, i)
        if a is None or b is None:
            return None
        return 1 if a > b else 0
    return f


def sig_breakout(closes, entry=20, exit=10, **_):
    def f(i):
        if i < max(entry, exit):
            return None
        if closes[i] > max(closes[i - entry:i]):
            return 1
        if closes[i] < min(closes[i - exit:i]):
            return 0
        return None
    return f


def sig_rsi(closes, period=14, buy_below=30, sell_above=55, **_):
    def f(i):
        r = C.rsi(closes, period, i)
        if r is None:
            return None
        if r < buy_below:
            return 1
        if r > sell_above:
            return 0
        return None
    return f


STRATEGIES = {"buyhold": sig_buyhold, "sma": sig_sma, "breakout": sig_breakout, "rsi": sig_rsi}
GRIDS = {
    "sma": {"fast": [10, 20, 50], "slow": [50, 100, 150, 200]},
    "breakout": {"entry": [20, 55, 100], "exit": [10, 20, 50]},
    "rsi": {"period": [7, 14], "buy_below": [25, 30, 35], "sell_above": [50, 55, 65]},
}


# ------------------------------------------------------------------ engine

def simulate(rows, signal, cost_bps=20, rf_annual=0.0):
    """Long/flat, all-in, one instrument. Returns a result dict with the daily equity curve."""
    cost = cost_bps / 10000.0
    rf_d = (1 + rf_annual) ** (1.0 / C.TRADING_DAYS) - 1
    closes = [r["close"] for r in rows]
    cash, shares, pending = 1.0, 0.0, None
    equity, trades, entry_val, days_in = [], [], None, 0
    for i, r in enumerate(rows):
        if i > 0:
            cash *= 1 + rf_d
        if pending is not None:
            px = r["open"] or r["close"]
            if pending == 1 and shares == 0:
                entry_val = cash
                shares, cash = cash * (1 - cost) / px, 0.0
                trades.append({"date": r["date"], "side": "buy", "price": px})
            elif pending == 0 and shares > 0:
                cash, shares = shares * px * (1 - cost), 0.0
                trades.append({"date": r["date"], "side": "sell", "price": px,
                               "pnl": cash / entry_val - 1})
            pending = None
        if shares > 0:
            days_in += 1
        equity.append({"date": r["date"], "equity": cash + shares * r["close"]})
        want = signal(i)
        if want is not None and want != (1 if shares > 0 else 0) and i < len(rows) - 1:
            pending = want
    if shares > 0:  # mark the open trade at the last close
        trades.append({"date": rows[-1]["date"], "side": "open", "price": closes[-1],
                       "pnl": shares * closes[-1] / entry_val - 1})
    return stats(equity, trades, days_in, rf_annual)


def stats(equity, trades, days_in, rf_annual):
    vals = [e["equity"] for e in equity]
    n = len(vals)
    years = max(n - 1, 1) / float(C.TRADING_DAYS)
    total = vals[-1] / vals[0] - 1
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1 if vals[-1] > 0 else -1.0
    vol = C.ann_vol(C.daily_returns(vals))
    closed = [t for t in trades if "pnl" in t]
    wins = [t for t in closed if t["pnl"] > 0]
    return {
        "start": equity[0]["date"], "end": equity[-1]["date"], "days": n,
        "total": total, "cagr": cagr, "vol": vol,
        "sharpe": (cagr - rf_annual) / vol if vol else None,
        "mdd": C.max_drawdown(vals),
        "trades": sum(1 for t in trades if t["side"] == "buy"),
        "win_rate": len(wins) / len(closed) if closed else None,
        "exposure": days_in / float(n),
        "equity": equity, "trade_log": trades,
    }


def load_series(h, symbol=None, fund=None):
    if fund:
        rows = C.nav_series(h, fund)
        if len(rows) < 60:
            sys.exit("only %d NAV days for %r. Fund history grows by one day each time you run "
                     "`pkdata.py mufap`; backtests need about 60 or more." % (len(rows), fund))
        return fund, rows
    p = C.price_path(h, symbol)
    if not os.path.exists(p):
        sys.exit("no price file for %s: run `pkdata.py psx %s` first" % (symbol, symbol))
    return symbol.upper(), C.read_prices(p)


def params_from(a, strat):
    keys = {"sma": ["fast", "slow"], "breakout": ["entry", "exit"],
            "rsi": ["period", "buy_below", "sell_above"]}.get(strat, [])
    return {k: getattr(a, k) for k in keys if getattr(a, k) is not None}


def line(label, s):
    return [label, s["start"] + " .. " + s["end"], C.fmt_pct(s["total"]), C.fmt_pct(s["cagr"]),
            C.fmt_pct(s["mdd"]), "n/a" if s["sharpe"] is None else "%.2f" % s["sharpe"],
            s["trades"], C.fmt_pct(s["win_rate"], 0) if s["win_rate"] is not None else "n/a",
            "%.0f%%" % (100 * s["exposure"])]


HEAD = ["Run", "Period", "Return", "CAGR", "Max DD", "Sharpe", "Trades", "Win", "In mkt"]


def optimize(rows, strat, cost, rf, split=0.7):
    cut = int(len(rows) * split)
    ins, outs = rows[:cut], rows[cut:]
    grid = GRIDS[strat]
    best = None
    for combo in itertools.product(*grid.values()):
        p = dict(zip(grid.keys(), combo))
        if strat == "sma" and p["fast"] >= p["slow"]:
            continue
        s = simulate(ins, STRATEGIES[strat]([r["close"] for r in ins], **p), cost, rf)
        score = s["sharpe"] if s["sharpe"] is not None else -9
        if best is None or score > best[0]:
            best = (score, p, s)
    _, p, s_in = best
    # Out of sample: run over the whole series so indicators are warm, then keep the tail only.
    closes = [r["close"] for r in rows]
    sig = STRATEGIES[strat](closes, **p)
    s_out = simulate(outs, lambda i: sig(i + cut), cost, rf)
    return p, s_in, s_out


def write_equity(path, s):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "equity"])
        for e in s["equity"]:
            w.writerow([e["date"], round(e["equity"], 6)])


def cmd_run(a, h, cfg):
    name, rows = load_series(h, a.symbol, a.fund)
    if a.start:
        rows = [r for r in rows if r["date"] >= a.start]
    if len(rows) < 30:
        sys.exit("not enough data (%d days)" % len(rows))
    cost, rf = cfg["cost_bps_per_side"], cfg["risk_free_annual"]
    closes = [r["close"] for r in rows]
    bh = simulate(rows, sig_buyhold(closes), cost, rf)
    if a.optimize:
        if a.strategy not in GRIDS:
            sys.exit("--optimize works with: " + ", ".join(GRIDS))
        split = float(cfg.get("train_split", 0.7))
        p, s_in, s_out = optimize(rows, a.strategy, cost, rf, split)
        cut = int(len(rows) * split)
        bh_out = simulate(rows[cut:], sig_buyhold(closes[cut:]), cost, rf)
        print("%s %s, best parameters on the first 70%%: %s" % (name, a.strategy, p))
        print(C.md_table(HEAD, [line("in-sample (tuned)", s_in), line("OUT-OF-SAMPLE", s_out),
                                line("buy & hold, same span", bh_out)]))
        print("\nJudge it by the out-of-sample line. A big gap between the two means the "
              "parameters were fitted to noise.")
        return 0
    p = params_from(a, a.strategy)
    s = simulate(rows, STRATEGIES[a.strategy](closes, **p), cost, rf)
    print("%s, %s %s, costs %s bps a side, cash yield %.1f%%" % (
        name, a.strategy, p or "", cost, rf * 100))
    print(C.md_table(HEAD, [line(a.strategy, s), line("buy & hold", bh)]))
    if a.trades:
        print("\nTrades:")
        for t in s["trade_log"]:
            print("  %s %-4s %.2f%s" % (t["date"], t["side"], t["price"],
                                        "  %s" % C.fmt_pct(t["pnl"]) if "pnl" in t else ""))
    if a.equity_csv:
        write_equity(a.equity_csv, s)
        print("\nequity curve saved to " + a.equity_csv)
    return 0


def cmd_compare(a, h, cfg):
    name, rows = load_series(h, a.symbol, a.fund)
    cost, rf = cfg["cost_bps_per_side"], cfg["risk_free_annual"]
    closes = [r["close"] for r in rows]
    out = [line(k, simulate(rows, f(closes), cost, rf)) for k, f in STRATEGIES.items()]
    print("%s, default parameters, costs %s bps a side" % (name, cost))
    print(C.md_table(HEAD, out))
    return 0


# ------------------------------------------------------------------ momentum rotation

def momentum(h, cfg, symbols, lookback=126, hold=3, rebalance=21, start=None):
    """Every `rebalance` sessions, hold the top `hold` symbols by `lookback` return, equally
    weighted, but only those with a positive return (otherwise that slot sits in cash)."""
    cost = cfg["cost_bps_per_side"] / 10000.0
    rf_d = (1 + cfg["risk_free_annual"]) ** (1.0 / C.TRADING_DAYS) - 1
    data = {}
    for s in symbols:
        p = C.price_path(h, s)
        if os.path.exists(p):
            data[s] = {r["date"]: r for r in C.read_prices(p)}
    if len(data) < 2:
        sys.exit("momentum needs price files for at least two symbols")
    dates = sorted(set(d for m in data.values() for d in m))
    if start:
        dates = [d for d in dates if d >= start]
    last_close, hist = {}, {s: [] for s in data}
    cash, shares, pending = 1.0, {}, None
    equity, trades, days_in = [], [], 0
    for i, d in enumerate(dates):
        if i > 0:
            cash *= 1 + rf_d
        for s in data:
            if d in data[s]:
                last_close[s] = data[s][d]["close"]
            if s in last_close:
                hist[s].append(last_close[s])
        if pending is not None:  # execute at today's open
            px = {s: (data[s][d]["open"] if d in data[s] else last_close.get(s)) for s in data}
            value = cash + sum(q * px[s] for s, q in shares.items())
            slot = value * (1 - cost) / hold  # leave room for fees so cash never goes negative
            target = {s: slot for s in pending}
            new, fees = {}, 0.0
            for s in set(shares) | set(target):
                cur, tgt = shares.get(s, 0) * px[s], target.get(s, 0)
                if abs(tgt - cur) > 1e-9:
                    fees += abs(tgt - cur) * cost
                    trades.append({"date": d, "symbol": s, "side": "buy" if tgt > cur else "sell"})
                if tgt > 0:
                    new[s] = tgt / px[s]
            cash = value - sum(target.values()) - fees
            shares, pending = new, None
        if shares:
            days_in += 1
        eq = cash + sum(q * last_close[s] for s, q in shares.items())
        equity.append({"date": d, "equity": eq})
        if i % rebalance == 0 and i < len(dates) - 1:
            moms = []
            for s, hs in hist.items():
                if len(hs) > lookback and hs[-1 - lookback]:
                    moms.append((hs[-1] / hs[-1 - lookback] - 1, s))
            moms.sort(reverse=True)
            pending = [s for m, s in moms[:hold] if m > 0]
    res = stats(equity, trades, days_in, cfg["risk_free_annual"])
    res["holdings"] = sorted(shares)
    res["trade_log"] = trades
    return res


def cmd_momentum(a, h, cfg):
    symbols = [s.upper() for s in (a.symbols or cfg["watchlist"])]
    r = momentum(h, cfg, symbols, a.lookback, a.hold, a.rebalance, a.start)
    rows = [line("momentum top %d" % a.hold, r)]
    bench = cfg["benchmark"].upper()
    if os.path.exists(C.price_path(h, bench)):
        br = [x for x in C.read_prices(C.price_path(h, bench)) if x["date"] >= r["start"]]
        rows.append(line(bench + " buy & hold", simulate(br, lambda i: 1, cfg["cost_bps_per_side"],
                                                         cfg["risk_free_annual"])))
    print("Momentum rotation over %d symbols: %d-day lookback, top %d, rebalance every %d sessions"
          % (len(symbols), a.lookback, a.hold, a.rebalance))
    print(C.md_table(HEAD, rows))
    print("\nHolding now: %s" % (", ".join(r["holdings"]) or "cash"))
    if a.equity_csv:
        write_equity(a.equity_csv, r)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "compare"):
        p = sub.add_parser(name)
        p.add_argument("symbol", nargs="?")
        p.add_argument("--fund")
        if name == "run":
            p.add_argument("--strategy", default="sma", choices=list(STRATEGIES))
            p.add_argument("--fast", type=int)
            p.add_argument("--slow", type=int)
            p.add_argument("--entry", type=int)
            p.add_argument("--exit", type=int)
            p.add_argument("--period", type=int)
            p.add_argument("--buy-below", type=float)
            p.add_argument("--sell-above", type=float)
            p.add_argument("--optimize", action="store_true")
            p.add_argument("--start", help="YYYY-MM-DD")
            p.add_argument("--trades", action="store_true", help="list every trade")
            p.add_argument("--equity-csv")
    p = sub.add_parser("momentum")
    p.add_argument("--symbols", nargs="*")
    p.add_argument("--lookback", type=int, default=126)
    p.add_argument("--hold", type=int, default=3)
    p.add_argument("--rebalance", type=int, default=21)
    p.add_argument("--start")
    p.add_argument("--equity-csv")
    a = ap.parse_args(argv)
    if a.cmd in ("run", "compare") and not (a.symbol or a.fund):
        ap.error("give a SYMBOL or --fund NAME")
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"run": cmd_run, "compare": cmd_compare, "momentum": cmd_momentum}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
