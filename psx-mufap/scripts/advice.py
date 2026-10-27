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


def price_calc(broker, qty, price, stop, target, buying=False):
    """The price calculator attached to every suggestion: rupees at the stop and at the target.

    `price` is today's close (holdings) or the entry (buy ideas). With buying=True the purchase
    charges are counted too. Charges use the broker's schedule (portfolio.estimate_charges).
    """
    import portfolio as PF
    if not qty or price is None or stop is None or target is None:
        return None
    qty = int(qty)

    def fees(px, side):
        return sum(PF.estimate_charges(broker, qty, px, side))

    buy_fees = fees(price, "buy") if buying else 0.0
    sell_stop, sell_target = fees(stop, "sell"), fees(target, "sell")
    loss = qty * (price - stop) + buy_fees + sell_stop if price > stop else 0.0
    gain = qty * (target - price) - buy_fees - sell_target
    out = {"qty": qty, "price": round(price, 2), "stop": round(stop, 2), "target": round(target, 2),
           "value": round(qty * price, 2), "buy_fees": round(buy_fees, 2),
           "loss_at_stop": round(loss, 2), "gain_at_target": round(gain, 2),
           "stop_move_pct": stop / price - 1, "target_move_pct": target / price - 1,
           "reward_risk": round(gain / loss, 2) if loss > 0 else None,
           "breakeven_win_rate": loss / (loss + gain) if loss > 0 and gain > 0 else None,
           "breakeven_price": round(price + (buy_fees + fees(price, "sell")) / qty, 2)}
    return out


def calc_lines(c, label):
    """Plain-language lines for one price calculation."""
    if not c:
        return []
    out = ["%s: %d shares at %.2f = %s%s" % (label, c["qty"], c["price"], C.fmt_pkr(c["value"]),
                                              " + %s charges" % C.fmt_pkr(c["buy_fees"]) if c["buy_fees"] else "")]
    if c["loss_at_stop"]:
        out.append("  falls to the stop %.2f (%s): lose about %s after charges" % (
            c["stop"], C.fmt_pct(c["stop_move_pct"]), C.fmt_pkr(c["loss_at_stop"])))
    else:
        out.append("  already at or below the stop %.2f" % c["stop"])
    if c.get("held") and c["loss_at_stop"] == 0:
        out.append("  the stop has been hit, so the suggestion is to sell (the target no longer applies)")
    else:
        out.append("  rises to the target %.2f (%s): %s about %s after charges" % (
            c["target"], C.fmt_pct(c["target_move_pct"]), "gain" if c["gain_at_target"] >= 0 else "still lose",
            C.fmt_pkr(abs(c["gain_at_target"]))))
    if c.get("held"):
        out.append("  selling today vs what you paid (avg %.2f): %s %s after charges; at the stop: %s %s" % (
            c["avg_cost"], "gain" if c["vs_cost_now"] >= 0 else "loss", C.fmt_pkr(abs(c["vs_cost_now"])),
            "gain" if c["vs_cost_at_stop"] >= 0 else "loss", C.fmt_pkr(abs(c["vs_cost_at_stop"]))))
    extra = []
    if c["reward_risk"] is not None:
        extra.append("reward-to-risk %.1f to 1" % c["reward_risk"])
    if c["breakeven_win_rate"] is not None:
        extra.append("worth it if it works more than %.0f%% of the time" % (100 * c["breakeven_win_rate"]))
    extra.append("break-even after charges %.2f" % c["breakeven_price"])
    out.append("  " + "; ".join(extra))
    return out


def _bench_3m(h, cfg):
    p = C.price_path(h, cfg["benchmark"])
    if not os.path.exists(p):
        return None
    cl = [r["close"] for r in C.read_prices(p)]
    return cl[-1] / cl[-64] - 1 if len(cl) > 64 else None


def review_holdings(h, cfg, lg, s):
    """One suggestion per holding. `s` is portfolio.summary()."""
    import portfolio as PF
    out = []
    total = s["value"] + (s["cash"] or 0)
    b3 = _bench_3m(h, cfg)
    today = dt.date.today().isoformat()
    soon = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    market = P.load_payouts(h)
    for p in s["holdings"]:
        sym = p["symbol"]
        r = {"symbol": sym, "qty": p["qty"], "avg_cost": round(p["avg_cost"], 2), "price": p["price"],
             "status": p.get("status"), "net_pl": p.get("net_pl"), "net_pl_pct": p.get("net_pl_pct"),
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
        bk = max(p["brokers"], key=p["brokers"].get) if p.get("brokers") else lg.get("default_broker")
        r["broker"] = bk
        r["calc"] = price_calc(lg["brokers"].get(bk) if bk else None, p["qty"], px, r["stop"], st["target"])
        if r["calc"]:
            b = lg["brokers"].get(bk) if bk else None
            sell_now = sum(PF.estimate_charges(b, p["qty"], px, "sell"))
            r["calc"].update(
                held=True, avg_cost=round(p["avg_cost"], 2),
                vs_cost_now=round(p["qty"] * (px - p["avg_cost"]) - sell_now, 2),
                vs_cost_at_stop=round(p["qty"] * (r["stop"] - p["avg_cost"]) -
                                      sum(PF.estimate_charges(b, p["qty"], r["stop"], "sell")), 2),
                breakeven_price=round(p["avg_cost"] + sell_now / p["qty"], 2))
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


def size_for(cfg, capital, spendable, risk_left, entry, risk, lot=1):
    """(qty, the limit that bound, all limits): the smallest of the four sizing rules, in lots."""
    limits = {"risk per trade": int(capital * setting(cfg, "risk_per_trade") / risk),
              "max position": int(capital * setting(cfg, "max_position_pct") / entry)}
    if spendable is not None:
        limits["cash after reserve"] = int(max(spendable, 0) / (entry * 1.005))
    if risk_left is not None:
        limits["open-risk budget"] = int(max(risk_left, 0) / risk)
    binding = min(limits, key=limits.get)
    return limits[binding] // lot * lot, binding, limits


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
            qty, binding, _ = size_for(cfg, capital, spendable, risk_left, entry, risk, lot)
            idea["limited_by"] = binding
            if qty > 0:
                c, o = PF.estimate_commission(lg["brokers"].get(broker) if broker else None, qty, entry)
                idea.update(qty=qty, cost=round(qty * entry + c + o, 2), est_fees=round(c + o, 2), broker=broker,
                            risk_pkr=round(qty * risk, 2))
                idea["calc"] = price_calc(lg["brokers"].get(broker) if broker else None, qty, entry,
                                          st["initial"], st["target"], buying=True)
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


def attach_opinion(row, theirs, ours):
    """Put a third party's signal (signals.py) beside our suggestion, with whether they agree."""
    import signals as SG
    if theirs:
        row["theirs"] = {"source": "PakistaniBulls", "signal": theirs["signal"], "stance": theirs.get("stance"),
                         "text": SG.describe(theirs), "read_at": theirs.get("read_at"),
                         "agreement": SG.agreement(ours, theirs.get("stance"))}


def opinion_lines(items, updated):
    """items: [(symbol, ours, theirs-dict-or-None)]"""
    if updated is None:
        return []
    rows = [[s, ours, t["text"] if t else "no recent signal on file", (t or {}).get("agreement") or ""] for s, ours, t in items]
    return ["\nSECOND OPINION: PakistaniBulls candlestick signals (read %s; a different method, for comparison)" % updated,
            C.md_table(["Stock", "This tool", "PakistaniBulls", "Agree?"], rows)]


TICK = 0.01  # PSX price step for shares


def _down(p):
    return math.floor(p / TICK + 1e-9) * TICK


def order_tickets(res, lg, cfg):
    """Turn the suggestions into orders to type into a broker's app. Nothing here sends an order.

    SELL                -> sell at market (or a limit at the last price)
    TRIM                -> sell the excess with a limit at the last price
    HOLD / REVIEW       -> a stop-loss sell: trigger = the stop, limit = trigger less stop_limit_gap
                           (a gap so it still fills in a fast fall); plus an optional take-profit
    buy idea            -> a limit buy at the entry, then the stop-loss once it has filled
    Brokers whose stop-loss orders last one day (the preset's stop_validity) need them placed again
    each morning; the tickets say so.
    """
    gap = setting(cfg, "stop_limit_gap")
    out = []

    def validity(broker):
        b = lg["brokers"].get(broker) or {}
        v = b.get("stop_validity")
        return "today only: place it again each trading morning" if v == "day" else (
            "until cancelled" if v == "gtc" else "check how long your broker's app keeps it")

    for r in res["holdings"]:
        if r.get("price") is None:
            continue
        bk = r.get("broker") or lg.get("default_broker")
        if r["action"] == "SELL":
            out.append({"symbol": r["symbol"], "broker": bk, "side": "SELL", "type": "market", "qty": r["qty"],
                        "why": "at or below its stop", "validity": "today"})
            continue
        if r["action"] == "TRIM" and r.get("trim_qty"):
            out.append({"symbol": r["symbol"], "broker": bk, "side": "SELL", "type": "limit", "qty": r["trim_qty"],
                        "limit": round(r["price"], 2), "why": "trim to max_position_pct", "validity": "today"})
        if r.get("stop") and r["stop"] < r["price"]:
            out.append({"symbol": r["symbol"], "broker": bk, "side": "SELL", "type": "stop-loss", "qty": r["qty"],
                        "trigger": round(r["stop"], 2), "limit": round(_down(r["stop"] * (1 - gap)), 2),
                        "why": "protect the holding (%s stop)" % r.get("stop_source", ""), "validity": validity(bk)})
        if r.get("target") and r["target"] > r["price"]:
            out.append({"symbol": r["symbol"], "broker": bk, "side": "SELL", "type": "limit (take profit, optional)",
                        "qty": r["qty"], "limit": round(r["target"], 2), "why": "target", "validity": "your choice"})
    for i in res["buy"]:
        if not i.get("qty"):
            continue
        bk = i.get("broker") or lg.get("default_broker")
        out.append({"symbol": i["symbol"], "broker": bk, "side": "BUY", "type": "limit", "qty": i["qty"],
                    "limit": round(i["entry"], 2), "why": "buy idea (check the live price first)", "validity": "today"})
        out.append({"symbol": i["symbol"], "broker": bk, "side": "SELL", "type": "stop-loss (after the buy fills)",
                    "qty": i["qty"], "trigger": round(i["stop"], 2), "limit": round(_down(i["stop"] * (1 - gap)), 2),
                    "why": "protect the new position", "validity": validity(bk)})
    return out


def ticket_lines(tickets):
    if not tickets:
        return []
    rows = [[t["symbol"], t["side"], t["type"], t["qty"], "%.2f" % t["trigger"] if t.get("trigger") else "",
             "%.2f" % t["limit"] if t.get("limit") else ("market" if t["type"] == "market" else ""),
             t.get("broker") or "", t["validity"]] for t in tickets]
    return ["\nORDER TICKETS (type them into your broker's app yourself; nothing is sent from here)",
            C.md_table(["Stock", "Side", "Order", "Qty", "Trigger", "Limit", "Broker", "Valid"], rows),
            "A stop-loss order waits for the trigger price, then becomes a limit order at the limit price "
            "(set stop_limit_gap below the trigger so it still fills in a fast fall). Your app may not let a "
            "stop-loss and a take-profit hold the same shares at once: the stop matters more."]


def advise(h, cfg, args):
    import portfolio as PF
    lg = PF.load(h)
    s = PF.summary(h, lg)
    hold = review_holdings(h, cfg, lg, s)
    ideas, info = buy_ideas(h, cfg, lg, s, args.buy, args.all, args.shariah, args.sector, args.candidates, hold)
    res = {"date": dt.date.today().isoformat(), "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "holdings": hold, "buy": ideas, "info": info,
           "risk_profile": cfg.get("risk_profile"),
           "prices": "live" if C.LIVE["quotes"] else "end of day",
           "settings": {k: setting(cfg, k) for k in SHOWN},
           "summary": {k: s[k] for k in ("value", "cost", "unrealised", "realised", "dividends", "fees", "cash")}}
    import signals as SG
    found, snap = SG.lookup(h, cfg, [r["symbol"] for r in hold] + [i["symbol"] for i in ideas])
    for r in hold:
        attach_opinion(r, found.get(r["symbol"]), r.get("action"))
    for i in ideas:
        attach_opinion(i, found.get(i["symbol"]), "BUY")
    res["second_opinion"] = {"source": "PakistaniBulls", "updated": snap.get("updated")} if snap else None
    res["tickets"] = order_tickets(res, lg, cfg)
    d = os.path.join(h, "advice")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, res["date"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    return res


def cmd_advise(a, h, cfg):
    import freshness as F
    F.decide(a, h, cfg, F.scope(h, cfg, None, a.all), payouts=True)
    res = advise(h, cfg, a)
    if a.json:
        print(json.dumps(res, indent=1, default=str))
        return 0
    if res["holdings"]:
        print("YOUR HOLDINGS")
        import portfolio as PF
        print(C.md_table(["Stock", "Action", "Price", "Stop", "Target", "P/L if sold now", "Why"],
                         [[r["symbol"], r["action"], "n/a" if r.get("price") is None else "%.2f" % r["price"],
                           "n/a" if r.get("stop") is None else "%.2f%s" % (r["stop"], "*" if r.get("stop_source") == "yours" else ""),
                           "n/a" if r.get("target") is None else "%.2f" % r["target"],
                           "%s %s" % (PF.paint(r.get("status")), C.fmt_pct(r.get("net_pl_pct"))), r["why"] + ("; " + "; ".join(r["notes"]) if r["notes"] else "")]
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
    so = res.get("second_opinion")
    for line in opinion_lines([(r["symbol"], r["action"], r.get("theirs")) for r in res["holdings"]] +
                              [(i["symbol"], "BUY", i.get("theirs")) for i in res["buy"]], so and so["updated"]):
        print(line)
    calc = [l for r in res["holdings"] for l in calc_lines(r.get("calc"), "%s (%s), you hold" % (r["symbol"], r["action"]))]
    calc += [l for i in res["buy"] for l in calc_lines(i.get("calc"), "%s (BUY idea), buying" % i["symbol"])]
    if calc:
        print("\nPRICE CALCULATOR (from the %s, after estimated broker charges)" % (
            "live price" if res.get("prices") == "live" else "last close"))
        print("\n".join(calc))
    for line in ticket_lines(res.get("tickets")):
        print(line)
    st = res["settings"]
    print("\nStops: %.1f x average daily move, %.0f-%.0f%% below entry, trailing upward. Sizing: %.1f%% of "
          "capital at risk per idea, max %.0f%% per stock, %d holdings, %.0f%% cash reserve. "
          "See every setting: risk.py settings; change style: risk.py quiz." % (
              st["stop_atr_mult"], 100 * st["min_stop_pct"], 100 * st["max_stop_pct"], 100 * st["risk_per_trade"],
              100 * st["max_position_pct"], st["max_holdings"], 100 * st["cash_reserve_pct"]))
    print("These are rule-based suggestions from past prices, not investment advice. Prices are %s; "
          "check the live price and your own judgement before placing any order with your broker." % (
              "live quotes from the PSX data portal, which can lag the exchange" if res.get("prices") == "live"
              else "the last close"))
    return 0


def check(h, cfg, symbol, entry=None, stop=None, capital=None):
    """Everything about one share in one place: should I buy (or keep) it, and the rupees either way."""
    import portfolio as PF
    import propose
    import rank
    symbol = symbol.upper()
    path = C.price_path(h, symbol)
    if not os.path.exists(path):
        raise ValueError("no prices on file for %s: fetch them first (--fetch, or pkdata.py psx %s)" % (symbol, symbol))
    rows = C.read_prices(path)
    lg = PF.load(h)
    s = PF.summary(h, lg)
    held = {p["symbol"]: p for p in s["holdings"]}
    m = rank.stock_metrics(rows, cfg["risk_free_annual"]) if len(rows) > 30 else {}
    info = rank.stock_info(h, cfg, symbol, payouts=P.load_payouts(h), price=rows[-1]["close"])
    strategies = cfg.get("strategies") or propose.DEFAULT_STRATEGIES
    ev = propose.evaluate(h, cfg, symbol, strategies)
    res = {"symbol": symbol, "price": rows[-1]["close"], "price_date": rows[-1]["date"], "metrics": m, "info": info,
           "prices": "live" if rows[-1].get("live") else "end of day",
           "test": ev, "risk_profile": cfg.get("risk_profile")}
    import signals as SG
    found, snap = SG.lookup(h, cfg, [symbol])
    res["second_opinion_updated"] = snap.get("updated") if snap else None
    if symbol in held:
        r = [x for x in review_holdings(h, cfg, lg, s) if x["symbol"] == symbol][0]
        res.update(held=True, action=r["action"], why=r["why"], notes=r["notes"], review=r, calc=r.get("calc"))
        attach_opinion(res, found.get(symbol), res["action"])
        return res
    px = entry or rows[-1]["close"]
    st = stop_for(rows, px, rows[-1]["date"], cfg)
    stp = stop if stop is not None else st["initial"]
    if stp >= px:
        raise ValueError("the stop must be below the entry price")
    target = px + setting(cfg, "target_r") * (px - stp)
    cap = capital or (s["value"] + (s["cash"] or 0)) or float(cfg.get("capital") or 0)
    lot = int(cfg.get("lot_size") or 1)
    qty, binding = None, None
    if cap:
        rev = review_holdings(h, cfg, lg, s)
        spendable = (s["cash"] - setting(cfg, "cash_reserve_pct") * cap) if (s["cash"] is not None and not capital) else None
        risk_left = setting(cfg, "max_open_risk_pct") * cap - open_risk(rev)
        qty, binding, _ = size_for(cfg, cap, spendable, risk_left, px, px - stp, lot)
    broker = lg.get("default_broker")
    calc = price_calc(lg["brokers"].get(broker) if broker else None, qty or lot, px, stp, target, buying=True)
    if ev["pass"]:
        action, why = "BUY", "passes every check for your %s style: %s %s" % (cfg.get("risk_profile"), ev["strategy"], ev["params"])
    else:
        action, why = "NOT NOW", ev["why"]
    if len(held) >= int(setting(cfg, "max_holdings")) and action == "BUY":
        action, why = "NOT NOW", "you already hold %d shares, your style's limit (max_holdings)" % len(held)
    if qty == 0 and action == "BUY":
        why += "; but your sizing rules leave room for 0 shares (limited by %s)" % binding
    res.update(held=False, action=action, why=why, entry=px, stop=round(stp, 2), stop_source="yours" if stop is not None else "computed",
               target=round(target, 2), qty=qty, limited_by=binding, capital=cap, calc=calc, notes=[])
    attach_opinion(res, found.get(symbol), action)
    return res


def cmd_check(a, h, cfg):
    import freshness as F
    F.decide(a, h, cfg, [a.symbol], payouts=True)
    try:
        r = check(h, cfg, a.symbol, a.entry, a.stop, a.capital)
    except ValueError as e:
        sys.exit(str(e))
    if a.json:
        print(json.dumps(r, indent=1, default=str))
        return 0
    i, m, ev = r["info"], r["metrics"], r["test"]
    print("%s  %s%s%s" % (r["symbol"], i.get("name") or "", "  [%s]" % i["sector"] if i.get("sector") else "",
                          "  Shariah (KMI)" if i.get("shariah") else ""))
    print("%s %.2f on %s.  1m %s  3m %s  1y %s  volatility %s  max drawdown (1y) %s" % (
        "Live price" if r["prices"] == "live" else "Last close", r["price"], r["price_date"], C.fmt_pct(m.get("1m")), C.fmt_pct(m.get("3m")), C.fmt_pct(m.get("1y")),
        C.fmt_pct(m.get("vol")), C.fmt_pct(m.get("mdd"))))
    d = i.get("dividends") or {}
    if d.get("yield_ttm") is not None:
        print("Dividend yield (12 months) %s%s" % (C.fmt_pct(d["yield_ttm"]),
                                                   "; next book closure %s" % d["upcoming"]["bc_from"] if d.get("upcoming") else ""))
    if ev.get("strategy"):
        print("Backtest: best rule %s %s; on the untested %s: CAGR %s (buy-and-hold %s), max drawdown %s; signal today %s" % (
            ev["strategy"], ev["params"], "%s..%s" % (ev["out"]["start"], ev["out"]["end"]), C.fmt_pct(ev["out"]["cagr"]),
            C.fmt_pct(ev["out_buyhold"]["cagr"]), C.fmt_pct(ev["out"]["mdd"]), "LONG" if ev["signal"] == 1 else "flat"))
    print("\nVERDICT (%s style): %s. %s" % (r["risk_profile"], r["action"], r["why"]))
    for n in r["notes"]:
        print("  note: " + n)
    if r["held"]:
        rv = r["review"]
        print("You hold %d at an average %.2f; stop %.2f (%s), target %.2f." % (
            rv["qty"], rv["avg_cost"], rv["stop"], rv["stop_source"], rv["target"]))
        if r.get("calc"):
            print("\nPRICE CALCULATOR (after estimated broker charges)")
            print("\n".join(calc_lines(r["calc"], "You hold")))
    else:
        print("Entry %.2f, stop %.2f (%s, %s), target %.2f (%s)." % (
            r["entry"], r["stop"], r["stop_source"], C.fmt_pct(r["stop"] / r["entry"] - 1), r["target"],
            C.fmt_pct(r["target"] / r["entry"] - 1)))
        if r["qty"] is not None:
            print("Size for capital %s: %d shares (limited by %s)." % (C.fmt_pkr(r["capital"]), r["qty"], r["limited_by"]))
        else:
            print("No capital on record: the calculator shows one board lot. Pass --capital, or record cash.")
        print("\nPRICE CALCULATOR (after estimated broker charges)")
        print("\n".join(calc_lines(r["calc"], "Buying")))
    for line in opinion_lines([(r["symbol"], r["action"], r.get("theirs"))], r.get("second_opinion_updated")):
        print(line)
    print("\nRule-based, from past prices; not investment advice. Check the live price before any order.")
    return 0


def cmd_orders(a, h, cfg):
    import freshness as F
    F.decide(a, h, cfg, F.scope(h, cfg, None, a.all), payouts=True)
    a.buy, a.shariah, a.sector, a.candidates = a.buy, a.shariah, None, None
    res = advise(h, cfg, a)
    if a.json:
        print(json.dumps(res["tickets"], indent=1))
        return 0
    lines = ticket_lines(res["tickets"])
    print("\n".join(lines[1:]) if lines else "No orders to place: no holdings to protect and no buy ideas today.")
    return 0
