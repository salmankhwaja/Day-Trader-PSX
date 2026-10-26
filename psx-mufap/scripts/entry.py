#!/usr/bin/env python3
"""psx-entry: watches a setup and says the moment it triggers: waiting, triggered or expired.

  entry.py check SYN07                   the share's setup from today's scanner run
  entry.py check OGDC --setup orb        opening-range breakout, from today's intraday trades
  entry.py check OGDC --level 305        a price you chose: triggered on a 5-minute close above it
  entry.py watch OGDC --every 60         keep checking until it triggers, expires or the market closes
  entry.py check OGDC --now "2026-10-26 10:15"   replay a moment (with cached intraday data)

The rules:
  orb     waiting while the opening range (the first orb_minutes) forms; triggered by the first
          5-minute close above the range high; expired if price falls back under the range middle
          first, if it has already run more than one range-width above the high (too late to chase),
          or within entry_cutoff_min of the close.
  level   (breakout, flag, high52, gap, surge, bounce, or --level) triggered by a 5-minute close at
          or above the level; expired when more than 3% above it (chasing) or near the close.
A trigger isn't an order: it's the moment to run psx-exit / psx-budget / psx-risk and, if all is
well, type the ticket into your app. Prices: today's intraday trades (intraday.py); if those aren't
reachable, the live market-watch price.

Writes <home>/trader/entry.json.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402


def _setup(h, symbol):
    s = desk.read(h, "setups.json", {}) or {}
    return next((x for x in s.get("setups", []) if x.get("symbol") == symbol), None)


def evaluate(h, cfg, symbol, setup=None, level=None, now=None, bars=None):
    import intraday as I
    import scanner
    now = now or C.pk_now()
    symbol = symbol.upper()
    st = _setup(h, symbol)
    kind = setup or ("level" if level else (st or {}).get("setup") or "orb")
    lvl = level or ((st or {}).get("trigger") if kind != "orb" else None)
    close = C.close_time(now.date())
    cutoff = close - dt.timedelta(minutes=desk.setting(cfg, "entry_cutoff_min")) if close else None
    state = C.market_state(now)
    res = {"symbol": symbol, "setup": kind, "at": now.isoformat(timespec="minutes"), "market": state}
    if bars is None:
        try:
            bars = I.to_bars(I.get(h, symbol, now.date().isoformat()), 5)
        except Exception:  # noqa: BLE001
            bars = []
    done = [b for b in bars if dt.datetime.fromisoformat(b["dt"]) + dt.timedelta(minutes=5) <= now]
    if kind == "orb":
        o = scanner.orb_status(done, int(desk.setting(cfg, "orb_minutes")), now)
        if not o:
            res.update(status="waiting", why="no trades yet today" if state != "weekend" else "the market is closed today")
            return res
        width = o["or_high"] - o["or_low"]
        res.update(level=o["or_high"], or_low=o["or_low"], or_mid=o["or_mid"], last=o["last"], last_time=o["last_time"])
        if not o["complete"]:
            if now.strftime("%H:%M") >= o["range_done"]:
                res.update(status="waiting", why="range set at %.2f-%.2f; waiting for the first 5-minute close after %s" % (
                    o["or_low"], o["or_high"], o["range_done"]))
            else:
                res.update(status="waiting", why="the opening range is still forming (until %s)" % o["range_done"])
        elif o["broke_out"]:
            k = next(i for i, b in enumerate(done) if b["t"] == o["breakout_bar"])
            after = done[k:]
            if any(b["close"] < o["or_mid"] for b in after[1:]):
                res.update(status="expired", why="broke out at %s but fell back under the range middle" % o["breakout_bar"])
            elif o["last"] > o["or_high"] + width:
                res.update(status="expired", why="already %.2f above the range high: more than one range-width, too late to chase"
                           % (o["last"] - o["or_high"]))
            else:
                res.update(status="triggered", why="the %s 5-minute bar closed at %.2f, above the range high %.2f" % (
                    o["breakout_bar"], done[k]["close"], o["or_high"]), trigger_bar=o["breakout_bar"])
        else:
            res.update(status="waiting", why="no 5-minute close above %.2f yet (last %.2f at %s)" % (
                o["or_high"], o["last"], o["last_time"]))
    else:
        if lvl is None:
            raise ValueError("no level: give --level PRICE, or run the scanner first")
        res["level"] = lvl
        last = done[-1]["close"] if done else None
        if last is None:
            import freshness as F
            snap = F.load_live(h)
            q = (snap or {}).get("quotes", {}).get(symbol)
            last = q["current"] if q else None
            res["source"] = "live market watch" if q else None
        res["last"] = last
        trig = next((b for b in done if b["close"] >= lvl), None)
        if last is None:
            res.update(status="waiting", why="no price yet today")
        elif last > lvl * 1.03:
            res.update(status="expired", why="%.2f is more than 3%% above the level %.2f: too late to chase" % (last, lvl))
        elif trig or (not done and last >= lvl):
            res.update(status="triggered", why="closed at or above %.2f%s" % (lvl, " at %s" % trig["t"] if trig else ""))
        else:
            res.update(status="waiting", why="last %.2f, under the level %.2f" % (last, lvl))
    if res["status"] in ("waiting", "triggered") and cutoff and now >= cutoff:
        res.update(status="expired", why="within %d minutes of the close: no new day-trade entries" %
                   desk.setting(cfg, "entry_cutoff_min"))
    if state in ("closed", "weekend") and res["status"] == "waiting" and now >= (close or now):
        res.update(status="expired", why="the market has closed")
    return res


def show(r):
    mark = {"triggered": "TRIGGERED", "waiting": "waiting", "expired": "expired"}[r["status"]]
    out = "%s %s (%s): %s - %s" % (r["at"][11:16], r["symbol"], r["setup"], mark, r["why"])
    if r["status"] == "triggered":
        out += "\n  Next: exitplan.py plan %s --write, then budget.py --write and risk.py check." % r["symbol"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("check", "watch"):
        p = sub.add_parser(n)
        p.add_argument("symbol")
        p.add_argument("--setup", choices=["orb", "level"])
        p.add_argument("--level", type=float)
        p.add_argument("--from-file", help="a saved intraday response for this share")
        p.add_argument("--json", action="store_true")
        if n == "check":
            p.add_argument("--now")
        else:
            p.add_argument("--every", type=int, default=60)
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    import intraday as I
    bars = None
    if a.from_file:
        bars = I.to_bars(I.fetch(h, a.symbol, a.from_file), 5)
    try:
        if a.cmd == "check":
            r = evaluate(h, cfg, a.symbol, a.setup, a.level, desk.now(a.now), bars)
            desk.write(h, "entry.json", r)
            print(json.dumps(r, indent=1) if a.json else show(r))
            return 0
        print("Watching %s every %d s (Ctrl+C to stop)." % (a.symbol.upper(), a.every))
        while True:
            r = evaluate(h, cfg, a.symbol, a.setup, a.level)
            desk.write(h, "entry.json", r)
            print(show(r), flush=True)
            if r["status"] != "waiting":
                if r["status"] == "triggered":
                    import alerts
                    alerts.notify("PSX entry", "%s triggered: %s" % (r["symbol"], r["why"]))
                return 0
            time.sleep(a.every)
    except ValueError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
