#!/usr/bin/env python3
"""Turn rankings and backtests into a proposed paper portfolio, then keep it under review.

  propose.py run [--all] [--shariah] [--sector X] [--pick 5] [--apply]
  propose.py review [--stop-loss 15] [--apply]

`run` works in three passes:
  1. Screen: rank the watchlist (or every liquid PSX share with --all) and keep the top
     --candidates (default 15) by score. Filters: --shariah, --sector, --min-volume.
  2. Test: for each candidate and each strategy (sma, breakout, rsi), tune parameters on the
     first 70% of its history and run the winner untouched on the last 30%. The strategy is
     chosen on the in-sample result only. A candidate passes when that out-of-sample run
       - beat the cash yield (risk_free_annual) after costs,
       - had a positive Sharpe ratio,
       - lost no more than --max-dd (default 35%) from peak to trough,
     and the strategy's signal is LONG today.
  3. Build: take the passing names by score, at most --max-per-sector (default 2) per sector,
     up to --pick names, skipping ones already held. Size them equally from --invest-pct of
     the account's cash, capped at --max-position (default 20%) of the account each.

Without --apply it only prints the proposal and saves it to <home>/proposals/<date>.json.
With --apply it books the buys in the paper account, recording each position's strategy so
`review` can tell when that strategy says get out.

`review` checks every stock held in the paper account: SELL when its strategy's signal has
turned flat, or when it is down more than --stop-loss % from its average cost. Otherwise HOLD.

Research and practice only: these are paper trades, never real orders, and a backtest that
passed is not a forecast.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import freshness as F  # noqa: E402
import backtest as B  # noqa: E402
import paper  # noqa: E402
from rank import rank_stocks  # noqa: E402

DEFAULT_STRATEGIES = ["sma", "breakout", "rsi"]


def current_signal(closes, strategy, params):
    """Replay the strategy to the last close and return its standing position (1 long, 0 flat)."""
    sig = B.STRATEGIES[strategy](closes, **params)
    state = 0
    for i in range(len(closes)):
        v = sig(i)
        if v is not None:
            state = v
    return state


def evaluate(h, cfg, symbol, strategies, max_dd=None):
    """Tune each strategy on the first train_split of history, keep the best in-sample, then judge
    it only on the untouched rest against the gates in your risk profile."""
    max_dd = float(cfg.get("gate_max_drawdown", 0.35)) if max_dd is None else max_dd
    split = float(cfg.get("train_split", 0.7))
    min_sharpe = float(cfg.get("gate_min_sharpe", 0.0))
    min_excess = float(cfg.get("gate_min_excess_return", 0.0))
    rows = C.read_prices(C.price_path(h, symbol))
    if len(rows) < 300:
        return {"symbol": symbol, "pass": False, "why": "under 300 days of history"}
    cost, rf = cfg["cost_bps_per_side"], cfg["risk_free_annual"]
    best = None
    for strat in strategies:
        p, s_in, s_out = B.optimize(rows, strat, cost, rf, split)
        key = s_in["sharpe"] if s_in["sharpe"] is not None else -9
        if best is None or key > best[0]:
            best = (key, strat, p, s_in, s_out)
    _, strat, p, s_in, s_out = best
    cut = int(len(rows) * split)
    closes = [r["close"] for r in rows]
    bh_out = B.simulate(rows[cut:], B.sig_buyhold(closes[cut:]), cost, rf)
    signal = current_signal(closes, strat, p)
    checks = [
        (s_out["cagr"] > rf + min_excess, "out-of-sample CAGR %s vs cash %s%s" % (
            C.fmt_pct(s_out["cagr"]), C.fmt_pct(rf), " + %s" % C.fmt_pct(min_excess) if min_excess else "")),
        ((s_out["sharpe"] if s_out["sharpe"] is not None else -9) > min_sharpe, "out-of-sample Sharpe %s (need over %.2f)" % (
            "n/a" if s_out["sharpe"] is None else "%.2f" % s_out["sharpe"], min_sharpe)),
        (s_out["mdd"] >= -max_dd, "out-of-sample max drawdown %s" % C.fmt_pct(s_out["mdd"])),
        (signal == 1, "signal today: %s" % ("LONG" if signal == 1 else "flat")),
    ]
    failed = [msg for ok, msg in checks if not ok]
    return {"symbol": symbol, "pass": not failed, "why": "; ".join(failed) if failed else "all checks passed",
            "strategy": strat, "params": p, "signal": signal,
            "in": {k: s_in[k] for k in ("start", "end", "total", "cagr", "sharpe", "mdd", "trades")},
            "out": {k: s_out[k] for k in ("start", "end", "total", "cagr", "sharpe", "mdd", "trades")},
            "out_buyhold": {k: bh_out[k] for k in ("total", "cagr", "mdd")},
            "price": closes[-1], "price_date": rows[-1]["date"]}


def build_proposal(h, cfg, a, exclude=None):
    """`exclude`: symbols never to pick (default: what the paper account already holds)."""
    ranked, _, notes = rank_stocks(h, cfg, a.symbols, "score", a.all, a.sector, a.shariah, a.min_volume)
    if not ranked:
        sys.exit("nothing to screen: download prices first")
    n_cand = a.candidates or int(cfg.get("candidates", 15))
    cands = ranked[:n_cand]
    strategies = a.strategies.split(",") if a.strategies else (cfg.get("strategies") or DEFAULT_STRATEGIES)
    max_dd = a.max_dd / 100.0 if a.max_dd is not None else None
    per_sector_cap = a.max_per_sector if a.max_per_sector is not None else int(cfg.get("max_per_sector", 2))
    evals = []
    for m in cands:
        e = evaluate(h, cfg, m["symbol"], strategies, max_dd)
        e.update({"score": m["score"], "sector": m.get("sector"), "shariah": m.get("shariah"),
                  "name": m.get("name"), "div_yield": m.get("div_yield")})
        evals.append(e)
    pf = paper.load(h) if os.path.exists(paper.ppath(h)) else None
    held = set(exclude) if exclude is not None else (set(pf["positions"]) if pf else set())
    picks, per_sector = [], {}
    for e in evals:
        if not e["pass"] or e["symbol"] in held:
            continue
        sec = e.get("sector") or "UNKNOWN"
        if per_sector.get(sec, 0) >= per_sector_cap:
            e["why"] += "; sector already has %d picks" % per_sector_cap
            continue
        per_sector[sec] = per_sector.get(sec, 0) + 1
        picks.append(e)
        if len(picks) >= a.pick:
            break
    orders = []
    if picks and pf:
        _, total = paper.valuation(h, cfg, pf)
        per = min(pf["cash"] * a.invest_pct / 100.0 / len(picks), total * a.max_position / 100.0)
        lot = int(cfg.get("lot_size") or 1)
        for e in picks:
            qty = int(per / e["price"]) // lot * lot
            if qty > 0:
                orders.append({"symbol": e["symbol"], "qty": qty, "price": e["price"],
                               "value": round(qty * e["price"], 2), "strategy": e["strategy"], "params": e["params"]})
    return {"date": dt.date.today().isoformat(), "scope": "all" if a.all else "watchlist",
            "filters": {"shariah": a.shariah, "sector": a.sector}, "screened": len(ranked),
            "candidates": evals, "picks": [e["symbol"] for e in picks], "orders": orders,
            "account": bool(pf)}


def cmd_run(a, h, cfg):
    F.decide(a, h, cfg, F.scope(h, cfg, a.symbols, a.all), payouts=True)
    prop = build_proposal(h, cfg, a)
    d = os.path.join(h, "proposals")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, prop["date"] + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prop, f, indent=1, default=str)
    print("Screened %d stocks, backtested the top %d. Out-of-sample = the last 30%% of history, "
          "untouched by tuning." % (prop["screened"], len(prop["candidates"])))
    rows = []
    for e in prop["candidates"]:
        o = e.get("out") or {}
        rows.append([e["symbol"] + (" ☪" if e.get("shariah") else ""), "%.0f" % (e.get("score") or 0),
                     e.get("strategy") or "-", C.fmt_pct(o.get("cagr")),
                     C.fmt_pct((e.get("out_buyhold") or {}).get("cagr")), C.fmt_pct(o.get("mdd")),
                     "PICK" if e["symbol"] in prop["picks"] else ("pass" if e["pass"] else "no")])
    print(C.md_table(["Stock", "Score", "Strategy", "OOS CAGR", "B&H OOS", "OOS max DD", "Result"], rows))
    for e in prop["candidates"]:
        if not e["pass"]:
            print("  %s: %s" % (e["symbol"], e["why"]))
    if not prop["orders"]:
        print("\nNo orders: %s" % ("no paper account yet (paper.py init)" if not prop["account"]
                                   else "nothing passed every check" if not prop["picks"] else "not enough cash"))
        return 0
    print("\nProposed paper buys:")
    for o in prop["orders"]:
        print("  BUY %-8s %6d @ %.2f = %s   (%s %s)" % (o["symbol"], o["qty"], o["price"], C.fmt_pkr(o["value"]),
                                                     o["strategy"], o["params"]))
    print("saved %s" % path)
    if not a.apply:
        print("\nNothing booked. Rerun with --apply to buy these in the paper account.")
        return 0
    pf = paper.load(h)
    for o in prop["orders"]:
        try:
            print(paper.do_buy(h, cfg, pf, o["symbol"], o["qty"], None, "proposal %s" % prop["date"],
                               meta={"strategy": o["strategy"], "params": o["params"], "proposed": prop["date"]}))
        except ValueError as e:
            print("skipped %s: %s" % (o["symbol"], e))
    paper.save(h, pf)
    return 0


def review(h, cfg, stop_loss):
    pf = paper.load(h)
    out = []
    for sym, pos in sorted(pf["positions"].items()):
        if pos.get("kind") != "stock":
            continue
        px, asof = paper.stock_price(h, sym)
        if px is None:
            out.append({"symbol": sym, "action": "HOLD", "why": "no price data"})
            continue
        change = px * pos["qty"] / pos["cost"] - 1 if pos["cost"] else 0
        meta = pos.get("meta") or {}
        action, why = "HOLD", "signal still long" if meta.get("strategy") else "no strategy attached"
        if change <= -stop_loss:
            action, why = "SELL", "stop-loss: %s from cost" % C.fmt_pct(change)
        elif meta.get("strategy"):
            closes = [r["close"] for r in C.read_prices(C.price_path(h, sym))]
            if current_signal(closes, meta["strategy"], meta.get("params") or {}) == 0:
                action, why = "SELL", "%s %s signal turned flat" % (meta["strategy"], meta.get("params"))
        out.append({"symbol": sym, "qty": pos["qty"], "price": px, "asof": asof, "change": change,
                    "action": action, "why": why})
    return pf, out


def cmd_review(a, h, cfg):
    F.decide(a, h, cfg, F.held_symbols(h), payouts=True)
    pf, out = review(h, cfg, a.stop_loss / 100.0)
    if not out:
        print("no stock positions to review")
        return 0
    print(C.md_table(["Stock", "P/L", "Action", "Why"],
                     [[r["symbol"], C.fmt_pct(r.get("change")), r["action"], r["why"]] for r in out]))
    sells = [r for r in out if r["action"] == "SELL"]
    if not sells:
        return 0
    if not a.apply:
        print("\nNothing sold. Rerun with --apply to book the sells.")
        return 0
    for r in sells:
        print(paper.do_sell(h, cfg, pf, r["symbol"], "all", None, "review: " + r["why"]))
    paper.save(h, pf)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--all", action="store_true")
    p.add_argument("--symbols", nargs="*")
    p.add_argument("--shariah", action="store_true")
    p.add_argument("--sector")
    p.add_argument("--min-volume", type=float)
    p.add_argument("--candidates", type=int, help="default: your risk profile's 'candidates'")
    p.add_argument("--pick", type=int, default=5)
    p.add_argument("--max-per-sector", type=int, help="default: your risk profile's 'max_per_sector'")
    p.add_argument("--max-dd", type=float, help="largest acceptable out-of-sample drawdown, %% (default: profile)")
    p.add_argument("--invest-pct", type=float, default=90.0)
    p.add_argument("--max-position", type=float, default=20.0, help="%% of account per name")
    p.add_argument("--strategies", help="comma list (default: your risk profile's 'strategies')")
    p.add_argument("--apply", action="store_true")
    F.add_args(p)
    p = sub.add_parser("review")
    p.add_argument("--stop-loss", type=float, default=15.0)
    p.add_argument("--apply", action="store_true")
    F.add_args(p)
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"run": cmd_run, "review": cmd_review}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
