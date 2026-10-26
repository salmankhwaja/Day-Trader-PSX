"""Sell / hold / buy suggestions for your real portfolio, each with a stop-loss.

Used by `portfolio.py advise` and the dashboard. Every number below comes from your risk
profile (profiles.py) and can be overridden in config.json; `risk.py settings` lists them all.
None of it is a forecast, and none of it places an order.

Stop-loss (per share)
  volatility  = average absolute day-to-day price move over the last vol_window sessions (PSX's free
                data has no intraday high/low, so this stands in for the usual ATR)
  initial     = entry - stop_atr_mult x volatility, kept between min_stop_pct and
                max_stop_pct below entry (not so tight that normal daily noise triggers it)
  trailing    = highest close since you bought - stop_atr_mult x today's volatility
  stop        = the higher of the two (it only ever moves up), unless you set your own with
                `portfolio.py stop SYMBOL PRICE`, which always wins
  target      = entry + target_r x (entry - initial stop)

Holdings
  SELL    the last close is at or below the stop
  TRIM    the position is more than max_position_pct of the portfolio (says how many to sell)
  REVIEW  falling trend (below its trend_fast- and trend_slow-day averages) and lagging the
          KSE-100 by more than review_lag_pct over 3 months: worth a look, not an automatic sell
  HOLD    none of the above (with distance to stop; and a note when the target is reached)
  Notes are added for an upcoming book closure (selling before it gives up the dividend).

Buy ideas
  The shares that pass `propose.py`'s screen-and-backtest gates (gate_* settings), excluding
  what you hold, while you hold fewer than max_holdings shares. Each is sized by the smallest of:
    risk_per_trade x capital / (entry - stop)       a stop-out costs at most this
    max_position_pct x capital / entry               no single share gets too big
    (cash - cash_reserve_pct x capital) / entry      the reserve is never spent
    remaining open-risk budget / (entry - stop)      all stops together cost at most
                                                     max_open_risk_pct x capital
  in board lots, with commission estimated from your default broker.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import psxinfo as P  # noqa: E402

import profiles  # noqa: E402

SHOWN = ["stop_atr_mult", "min_stop_pct", "max_stop_pct", "target_r", "risk_per_trade", "max_position_pct",
         "max_holdings", "cash_reserve_pct", "max_open_risk_pct"]
DEFAULTS = {k: profiles.PROFILES[profiles.DEFAULT_PROFILE][k] for k in SHOWN}


def setting(cfg, k):
    v = cfg.get(k)
    return float(v if v is not None else profiles.PROFILES[profiles.DEFAULT_PROFILE][k])


def volatility(closes, n=14, end=None):
    """Average absolute close-to-close move over n sessions ending at index `end`."""
    end = len(closes) - 1 if end is None else end
    if end < 1:
        return None
    start = max(1, end - n + 1)
    moves = [abs(closes[i] - closes[i - 1]) for i in range(start, end + 1)]
    return sum(moves) / len(moves) if moves else None


def stop_for(rows, entry, entry_date, cfg):
    """(stop, initial, trailing, target, vol) for a position entered at `entry` on `entry_date`."""
    closes = [r["close"] for r in rows]
    if not closes:
        return None
    k, cap, tr = setting(cfg, "stop_atr_mult"), setting(cfg, "max_stop_pct"), setting(cfg, "target_r")
    floor = setting(cfg, "min_stop_pct")
    idx = max([i for i, r in enumerate(rows) if r["date"] <= entry_date] or [len(rows) - 1])
    # Volatility as of the entry; if the history starts at the entry, use today's instead.
    n = int(setting(cfg, "vol_window"))
    v_entry = (volatility(closes, n, end=idx) if idx >= 5 else None) or volatility(closes, n) or 0.0
    initial = min(max(entry - k * v_entry, entry * (1 - cap)), entry * (1 - floor))
    since = [r["close"] for r in rows if r["date"] >= entry_date] or [closes[-1]]
    v_now = volatility(closes, n) or 0.0
    trailing = min(max(since) - k * v_now, max(since) * (1 - floor))
    stop = max(initial, trailing)
    return {"stop": round(stop, 2), "initial": round(initial, 2), "trailing": round(trailing, 2),
            "target": round(entry + tr * (entry - initial), 2), "volatility": round(v_now, 2),
            "stop_pct": (stop / closes[-1] - 1) if closes[-1] else None}


def _bench_3m(h, cfg):
    p = C.price_path(h, cfg["benchmark"])
    if not os.path.exists(p):
        return None
    cl = [r["close"] for r in C.read_prices(p)]
    return cl[-1] / cl[-64] - 1 if len(cl) > 64 else None


def review_holdings(h, cfg, lg, s):
    """One suggestion per holding. `s` is portfolio.summary()."""
    out = []
    total = s["value"] + (s["cash"] or 0)
    b3 = _bench_3m(h, cfg)
    today = dt.date.today().isoformat()
    soon = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    market = P.load_payouts(h)
    for p in s["holdings"]:
        sym = p["symbol"]
        r = {"symbol": sym, "qty": p["qty"], "avg_cost": round(p["avg_cost"], 2), "price": p["price"],
             "price_date": p["price_date"], "value": p["value"], "unrealised_pct": p["unrealised_pct"], "notes": []}
        path = C.price_path(h, sym)
        rows = C.read_prices(path) if os.path.exists(path) else []
        if not rows:
            r.update(action="NO DATA", why="no prices on file: pkdata.py psx %s" % sym, stop=lg["stops"].get(sym))
            out.append(r)
            continue
        st = stop_for(rows, p["avg_cost"], p["first_buy"], cfg)
        own = lg["stops"].get(sym)
        r.update(st)
        if own is not None:
            r["stop"], r["stop_source"] = own, "yours"
        else:
            r["stop_source"] = "trailing" if st["trailing"] > st["initial"] else "initial"
        px = rows[-1]["close"]
        closes = [x["close"] for x in rows]
        weight = (p["value"] or 0) / total if total else 0
        r["weight"] = weight
        tf, ts = int(setting(cfg, "trend_fast")), int(setting(cfg, "trend_slow"))
        s50, s200 = C.sma(closes, tf, len(closes) - 1), C.sma(closes, ts, len(closes) - 1)
        down = s50 is not None and s200 is not None and px < s50 and px < s200
        r3 = closes[-1] / closes[-64] - 1 if len(closes) > 64 else None
        lag = (r3 - b3) if r3 is not None and b3 is not None else None
        maxw = setting(cfg, "max_position_pct")
        if px <= r["stop"]:
            r["action"], r["why"] = "SELL", "closed at %.2f, at or below the stop of %.2f (%s)" % (px, r["stop"], r["stop_source"])
        elif weight > maxw and total:
            excess = int(((weight - maxw) * total) / px)
            lot = int(cfg.get("lot_size") or 1)
            excess = max(lot, excess // lot * lot)
            r["action"], r["why"] = "TRIM", "%.0f%% of the portfolio (limit %.0f%%): sell about %d" % (100 * weight, 100 * maxw, excess)
            r["trim_qty"] = excess
        elif down and lag is not None and lag < -setting(cfg, "review_lag_pct"):
            r["action"], r["why"] = "REVIEW", "below its %d- and %d-day averages and %s behind KSE-100 over 3 months" % (
                tf, ts, C.fmt_pct(-lag))
        else:
            r["action"] = "HOLD"
            r["why"] = "%s above the stop of %.2f" % (C.fmt_pct(px / r["stop"] - 1), r["stop"])
            if px >= st["target"]:
                r["notes"].append("target %.2f reached: consider taking some profit or keeping the trailing stop" % st["target"])
        c = P.load_company(h, sym) or {}
        for pay in list(c.get("payouts") or []) + [m for m in market if m["symbol"] == sym]:
            bc = pay.get("bc_from")
            if bc and today <= bc <= soon and pay.get("cash_pct"):
                r["notes"].append("book closure %s for %s: selling before then gives up this dividend" % (bc, pay["details"]))
                break
        out.append(r)
    order = {"SELL": 0, "TRIM": 1, "REVIEW": 2, "NO DATA": 3, "HOLD": 4}
    out.sort(key=lambda r: (order.get(r["action"], 9), r["symbol"]))
    return out


def open_risk(review):
    """Rupees lost if every holding fell to its stop today (holdings already below it count 0)."""
    tot = 0.0
    for r in review:
        if r.get("price") and r.get("stop") is not None and r["price"] > r["stop"]:
            tot += r["qty"] * (r["price"] - r["stop"])
    return round(tot, 2)


def buy_ideas(h, cfg, lg, s, n=3, all_=False, shariah=False, sector=None, candidates=None, review=None):
    import portfolio as PF
    import propose
    a = argparse.Namespace(symbols=None, all=all_, sector=sector, shariah=shariah, min_volume=None,
                           candidates=candidates, strategies=None, max_dd=None, max_per_sector=None,
                           pick=n, invest_pct=100.0, max_position=100.0)
    held = {p["symbol"] for p in s["holdings"]}
    capital = s["value"] + (s["cash"] or 0) or float(cfg.get("capital") or 0)
    slots = int(setting(cfg, "max_holdings")) - len(held)
    info = {"capital": capital, "cash": s["cash"], "slots": slots}
    if slots <= 0:
        info.update(screened=0, tested=0, rejected=[],
                    note="you already hold %d shares, the most your profile allows (max_holdings)" % len(held))
        return [], info
    prop = propose.build_proposal(h, cfg, a, exclude=held)
    review = review if review is not None else review_holdings(h, cfg, lg, s)
    risk_left = setting(cfg, "max_open_risk_pct") * capital - open_risk(review) if capital else None
    spendable = (s["cash"] - setting(cfg, "cash_reserve_pct") * capital) if s["cash"] is not None else None
    info.update(open_risk=open_risk(review), risk_budget=round(setting(cfg, "max_open_risk_pct") * capital, 2),
                spendable_cash=None if spendable is None else round(max(spendable, 0), 2))
    broker = lg.get("default_broker")
    lot = int(cfg.get("lot_size") or 1)
    ideas = []
    by = {e["symbol"]: e for e in prop["candidates"]}
    for sym in prop["picks"]:
        if sym in held:
            continue
        e = by[sym]
        rows = C.read_prices(C.price_path(h, sym))
        entry = rows[-1]["close"]
        st = stop_for(rows, entry, rows[-1]["date"], cfg)
        risk = entry - st["initial"]
        idea = {"symbol": sym, "name": e.get("name"), "sector": e.get("sector"), "shariah": e.get("shariah"),
                "entry": entry, "price_date": rows[-1]["date"], "stop": st["initial"], "target": st["target"],
                "risk_per_share": round(risk, 2), "stop_pct": st["initial"] / entry - 1,
                "strategy": e.get("strategy"), "params": e.get("params"), "score": e.get("score"),
                "oos_cagr": (e.get("out") or {}).get("cagr"), "oos_buyhold_cagr": (e.get("out_buyhold") or {}).get("cagr"),
                "oos_mdd": (e.get("out") or {}).get("mdd"), "div_yield": e.get("div_yield"), "qty": None}
        if capital and risk > 0:
            limits = {"risk per trade": int(capital * setting(cfg, "risk_per_trade") / risk),
                      "max position": int(capital * setting(cfg, "max_position_pct") / entry)}
            if spendable is not None:
                limits["cash after reserve"] = int(max(spendable, 0) / (entry * 1.005))
            if risk_left is not None:
                limits["open-risk budget"] = int(max(risk_left, 0) / risk)
            binding = min(limits, key=limits.get)
            qty = limits[binding] // lot * lot
            idea["limited_by"] = binding
            if qty > 0:
                c, o = PF.estimate_commission(lg["brokers"].get(broker) if broker else None, qty, entry)
                idea.update(qty=qty, cost=round(qty * entry + c + o, 2), est_fees=round(c + o, 2), broker=broker,
                            risk_pkr=round(qty * risk, 2))
                if spendable is not None:
                    spendable -= idea["cost"]
                if risk_left is not None:
                    risk_left -= idea["risk_pkr"]
        ideas.append(idea)
        if len(ideas) >= min(n, slots):
            break
    info.update(screened=prop["screened"], tested=len(prop["candidates"]),
                rejected=[{"symbol": e["symbol"], "why": e["why"]} for e in prop["candidates"] if not e["pass"]])
    return ideas, info


def advise(h, cfg, args):
    import portfolio as PF
    lg = PF.load(h)
    s = PF.summary(h, lg)
    hold = review_holdings(h, cfg, lg, s)
    ideas, info = buy_ideas(h, cfg, lg, s, args.buy, args.all, args.shariah, args.sector, args.candidates, hold)
    res = {"date": dt.date.today().isoformat(), "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "holdings": hold, "buy": ideas, "info": info,
           "risk_profile": cfg.get("risk_profile"),
           "settings": {k: setting(cfg, k) for k in SHOWN},
           "summary": {k: s[k] for k in ("value", "cost", "unrealised", "realised", "dividends", "fees", "cash")}}
    d = os.path.join(h, "advice")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, res["date"] + ".json"), "w") as f:
        json.dump(res, f, indent=1, default=str)
    return res


def cmd_advise(a, h, cfg):
    res = advise(h, cfg, a)
    if a.json:
        print(json.dumps(res, indent=1, default=str))
        return 0
    if res["holdings"]:
        print("YOUR HOLDINGS")
        print(C.md_table(["Stock", "Action", "Price", "Stop", "Target", "P/L", "Why"],
                         [[r["symbol"], r["action"], "n/a" if r.get("price") is None else "%.2f" % r["price"],
                           "n/a" if r.get("stop") is None else "%.2f%s" % (r["stop"], "*" if r.get("stop_source") == "yours" else ""),
                           "n/a" if r.get("target") is None else "%.2f" % r["target"],
                           C.fmt_pct(r.get("unrealised_pct")), r["why"] + ("; " + "; ".join(r["notes"]) if r["notes"] else "")]
                          for r in res["holdings"]]))
    else:
        print("No holdings recorded yet (portfolio.py buy ...). Buy ideas only.")
    info = res["info"]
    print("\nRisk profile: %s. Open risk (all stops hit): %s of a %s budget." % (
        res["risk_profile"], C.fmt_pkr(info.get("open_risk")), C.fmt_pkr(info.get("risk_budget"))))
    if info.get("note"):
        print("\nBUY IDEAS: none, because %s." % info["note"])
    else:
        print("\nBUY IDEAS: %d screened, top %d backtested, %d passed every check" % (
            info["screened"], info["tested"], info["tested"] - len(info["rejected"])))
    if res["buy"]:
        print(C.md_table(["Stock", "Entry", "Stop", "Target", "Qty", "Cost incl. fees", "Risk", "Sized by", "Why"],
                         [[i["symbol"] + (" ☪" if i.get("shariah") else ""), "%.2f" % i["entry"],
                           "%.2f (%s)" % (i["stop"], C.fmt_pct(i["stop_pct"])), "%.2f" % i["target"],
                           i["qty"] or "-", C.fmt_pkr(i.get("cost")) if i.get("qty") else "-",
                           C.fmt_pkr(i.get("risk_pkr")) if i.get("qty") else "-", i.get("limited_by") or "-",
                           "%s %s: out-of-sample CAGR %s vs buy-and-hold %s" % (
                               i["strategy"], i["params"], C.fmt_pct(i["oos_cagr"]), C.fmt_pct(i["oos_buyhold_cagr"]))]
                          for i in res["buy"]]))
        if not info["capital"]:
            print("Quantities need your capital: record holdings or cash (portfolio.py cash deposit AMOUNT), "
                  "or set \"capital\" in config.json.")
    elif not info.get("note"):
        print("Nothing passed every check today: no buy ideas. Holding cash is a valid outcome.")
    st = res["settings"]
    print("\nStops: %.1f x average daily move, %.0f-%.0f%% below entry, trailing upward. Sizing: %.1f%% of "
          "capital at risk per idea, max %.0f%% per stock, %d holdings, %.0f%% cash reserve. "
          "See every setting: risk.py settings; change style: risk.py quiz." % (
              st["stop_atr_mult"], 100 * st["min_stop_pct"], 100 * st["max_stop_pct"], 100 * st["risk_per_trade"],
              100 * st["max_position_pct"], st["max_holdings"], 100 * st["cash_reserve_pct"]))
    print("These are rule-based suggestions from past prices, not investment advice. Prices are the last "
          "close; check the live price and your own judgement before placing any order with your broker.")
    return 0
