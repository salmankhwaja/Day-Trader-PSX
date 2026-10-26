#!/usr/bin/env python3
"""psx-timemachine: before risking a rupee, replay the trade thousands of times from the share's own past.

  timemachine.py run                       the plan on file (trader/plan.json), 10,000 replays
  timemachine.py run --sims 20000 --seed 7 --write
  timemachine.py run --symbol OGDC --entry 300 --stop 291 --target 318 --days 10

Two answers, side by side:

1. Simulated futures. Swing plans: each replay strings together the share's own daily moves,
   drawn in 5-day blocks from its last two years (so calm and wild weeks stay intact), each day
   capped at PSX's daily price limit, for the plan's horizon. Day plans: each replay strings
   together 5-minute bars drawn from the same time of day on the days whose intraday trades are
   cached (intraday.py keeps each day it fetches), from now to the flat-by time; it needs at least
   10 cached sessions, otherwise it says so.
   Counted: target first, stop first, or still open at the end (and where it ended).

2. History. Every past day the plan's setup fired in this share (the scanner's rules, replayed
   over its five years; or every cached session's opening-range breakout), the same stop and target
   distances are applied: how often did the target come first?

Swing replays use closing prices (PSX's free daily series has no highs and lows): a stop can be
hit intraday earlier than a close shows, so real stops fire somewhat more often than shown.
The odds are a reality check, not a forecast: results, policy news or a market halt can do what
the last two years never did.

Writes <home>/trader/timemachine.json.
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402


def _outcome(path, entry, stop, target):
    """('target'|'stop'|'open', exit price, day index) for a list of (low, high, close) steps."""
    for i, (lo, hi, cl) in enumerate(path, 1):
        if lo <= stop:
            return "stop", stop, i
        if hi >= target:
            return "target", target, i
    return "open", path[-1][2] if path else entry, len(path)


def summarise(results, entry, stop):
    n = len(results)
    risk = entry - stop
    cnt = {k: sum(1 for r in results if r[0] == k) for k in ("target", "stop", "open")}
    rs = [(r[1] - entry) / risk for r in results] if risk > 0 else []
    opens = sorted(r[1] for r in results if r[0] == "open")
    out = {"n": n, "target_first": cnt["target"] / n if n else None, "stop_first": cnt["stop"] / n if n else None,
           "still_open": cnt["open"] / n if n else None, "avg_r": sum(rs) / len(rs) if rs else None,
           "median_steps": sorted(r[2] for r in results)[n // 2] if n else None}
    if opens:
        out["open_median_price"] = opens[len(opens) // 2]
    return out


def swing_sims(rows, entry, stop, target, days, sims, seed, cfg, lookback=500, block=5):
    closes = [r["close"] for r in rows][-(lookback + 1):]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 60:
        raise ValueError("under 60 days of prices: not enough to replay")
    pct = float(cfg.get("circuit_limit_pct", C.CIRCUIT_PCT)) / 100.0
    rnd = random.Random(seed)
    out = []
    for _ in range(sims):
        px, path = entry, []
        while len(path) < days:
            j = rnd.randrange(0, len(rets) - block + 1)
            for r in rets[j:j + block]:
                if len(path) >= days:
                    break
                r = max(min(r, math.log(1 + pct)), math.log(1 - pct))
                px *= math.exp(r)
                path.append((px, px, px))
        out.append(_outcome(path, entry, stop, target))
    return summarise(out, entry, stop)


def swing_history(rows, setup, entry, stop, target, days):
    """Every past day the setup fired: the same % stop and target distances from that day's close."""
    import scanner
    sp, tp = stop / entry - 1, target / entry - 1
    res = []
    for i in range(260 if setup else 30, len(rows) - days):
        if setup and not any(s["setup"] == setup for s in scanner.daily_setups(rows[:i + 1])):
            continue
        e = rows[i]["close"]
        path = [(r["close"] / e,) * 3 for r in rows[i + 1:i + 1 + days]]  # in multiples of the entry
        res.append(_outcome(path, 1.0, 1.0 + sp, 1.0 + tp))
    return summarise(res, 1.0, 1.0 + sp) if res else {"n": 0}


def _day_bars(h, symbol, day):
    import intraday as I
    return I.to_bars(I.load(h, symbol, day), 5)


def intraday_sims(h, symbol, plan, now, sims, seed):
    import intraday as I
    days = [d for d in I.cached_days(h, symbol) if d < now.date().isoformat()]
    if len(days) < 10:
        return None, len(days)
    by_slot = {}
    for d in days:
        bars = _day_bars(h, symbol, d)
        for k in range(1, len(bars)):
            o, prev = bars[k]["open"], bars[k - 1]["close"]
            if prev <= 0 or o <= 0:
                continue
            by_slot.setdefault(bars[k]["t"], []).append((o / prev, bars[k]["high"] / o, bars[k]["low"] / o, bars[k]["close"] / o))
    flat = plan.get("flat_by") or "15:20"
    slots = sorted(t for t in by_slot if now.strftime("%H:%M") <= t < flat)
    if not slots:
        return {"n": 0, "note": "no time left before the flat-by time"}, len(days)
    rnd = random.Random(seed)
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    out = []
    for _ in range(sims):
        px, path = entry, []
        for t in slots:
            g, hi, lo, cl = rnd.choice(by_slot[t])
            o = px * g
            path.append((o * lo, o * hi, o * cl))
            px = o * cl
        out.append(_outcome(path, entry, stop, target))
    return summarise(out, entry, stop), len(days)


def orb_history(h, symbol, plan, minutes):
    """Every cached session: did the ORB fire, and with the plan's distances, which came first?"""
    import intraday as I
    import scanner
    sp, tp = plan["stop"] / plan["entry"] - 1, plan["target"] / plan["entry"] - 1
    res = []
    for d in I.cached_days(h, symbol):
        bars = _day_bars(h, symbol, d)
        st = scanner.orb_status(bars, minutes)
        if not st or not st["broke_out"]:
            continue
        k = next(i for i, b in enumerate(bars) if b["t"] == st["breakout_bar"])
        e = bars[k]["close"]
        flat = plan.get("flat_by") or "15:20"
        path = [(b["low"] / e, b["high"] / e, b["close"] / e) for b in bars[k + 1:] if b["t"] < flat]
        res.append(_outcome(path, 1.0, 1.0 + sp, 1.0 + tp))
    return summarise(res, 1.0, 1.0 + sp) if res else {"n": 0}


def verdict(sim):
    if not sim or not sim.get("n"):
        return "not enough data to say"
    t, s = sim["target_first"], sim["stop_first"]
    if sim["still_open"] >= 0.6:
        return "mostly neither: the stop and target are far apart for this horizon, so it usually just drifts"
    if t >= s * 1.5:
        return "the target came first clearly more often"
    if s >= t * 1.5:
        return "the stop came first clearly more often"
    return "close to a coin flip"


def run(h, cfg, plan, sims=10000, seed=None, now=None):
    now = now or C.pk_now()
    seed = seed if seed is not None else int(now.strftime("%Y%m%d"))
    p = C.price_path(h, plan["symbol"])
    rows = C.read_prices(p, live=False) if os.path.exists(p) else []
    res = {"symbol": plan["symbol"], "style": plan["style"], "entry": plan["entry"], "stop": plan["stop"],
           "target": plan["target"], "sims": sims, "seed": seed, "made": now.isoformat(timespec="minutes")}
    if plan["style"] == "day":
        sim, ndays = intraday_sims(h, plan["symbol"], plan, now, sims, seed)
        res["cached_sessions"] = ndays
        res["simulated"] = sim
        res["history"] = orb_history(h, plan["symbol"], plan, int(desk.setting(cfg, "orb_minutes"))) \
            if plan.get("setup") == "orb" else None
        if sim is None:
            res["note"] = ("only %d earlier sessions of intraday trades are cached for %s; the intraday replay needs 10. "
                           "Each day intraday.py (or scanner.py orb) fetches it, another session is kept." % (ndays, plan["symbol"]))
    else:
        if len(rows) < 60:
            raise ValueError("not enough end-of-day prices for %s: pkdata.py psx %s" % (plan["symbol"], plan["symbol"]))
        days = int(plan.get("days") or 10)
        res["days"] = days
        res["simulated"] = swing_sims(rows, plan["entry"], plan["stop"], plan["target"], days, sims, seed, cfg)
        res["history"] = swing_history(rows, plan.get("setup") if plan.get("setup") in
                                       ("breakout", "flag", "bounce", "high52", "gap", "surge") else None,
                                       plan["entry"], plan["stop"], plan["target"], days)
        res["history_rule"] = plan.get("setup") or "any day (no setup in the plan)"
    res["verdict"] = verdict(res.get("simulated"))
    return res


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def show(r):
    lines = ["TIME MACHINE %s (%s): entry %.2f, stop %.2f, target %.2f; %d replays, seed %s" % (
        r["symbol"], r["style"], r["entry"], r["stop"], r["target"], r["sims"], r["seed"])]
    s = r.get("simulated")
    if s and s.get("n"):
        lines.append("  Simulated: target first %s, stop first %s, still open at the end %s%s; average %+.2fR" % (
            pct(s["target_first"]), pct(s["stop_first"]), pct(s["still_open"]),
            " (median there %.2f)" % s["open_median_price"] if s.get("open_median_price") else "", s["avg_r"] or 0))
    elif r.get("note"):
        lines.append("  Simulated: " + r["note"])
    hst = r.get("history")
    if hst and hst.get("n"):
        lines.append("  History (%s, %d times): target first %s, stop first %s, neither %s" % (
            r.get("history_rule", "opening-range breakouts in cached sessions"), hst["n"], pct(hst["target_first"]),
            pct(hst["stop_first"]), pct(hst["still_open"])))
    elif hst is not None:
        lines.append("  History: the setup never fired in the data on file")
    lines.append("  Verdict: %s." % r["verdict"])
    if r["style"] == "swing":
        lines.append("  (Closing prices only: real stops can trigger intraday, so they fire somewhat more often than this.)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--symbol")
    p.add_argument("--entry", type=float)
    p.add_argument("--stop", type=float)
    p.add_argument("--target", type=float)
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--style", choices=["day", "swing"], default=None)
    p.add_argument("--sims", type=int, default=10000)
    p.add_argument("--seed", type=int)
    p.add_argument("--now")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    if a.symbol:
        if None in (a.entry, a.stop, a.target):
            sys.exit("with --symbol, give --entry, --stop and --target")
        plan = {"symbol": a.symbol.upper(), "style": a.style or "swing", "entry": a.entry, "stop": a.stop,
                "target": a.target, "days": a.days, "setup": None, "flat_by": None}
    else:
        plan = desk.read(h, "plan.json")
        if not plan:
            sys.exit("no plan on file: exitplan.py plan SYMBOL --write (or give --symbol --entry --stop --target)")
    try:
        r = run(h, cfg, plan, a.sims, a.seed, desk.now(a.now))
    except ValueError as e:
        sys.exit(str(e))
    if a.write:
        desk.write(h, "timemachine.json", r)
    print(json.dumps(r, indent=1) if a.json else show(r))
    if not a.json:
        print(desk.DISCLAIMER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
