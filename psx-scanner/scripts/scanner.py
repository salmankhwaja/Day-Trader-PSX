#!/usr/bin/env python3
"""psx-scanner: find today's trade setups on PSX.

  scanner.py daily                 before the open: setups in the end-of-day charts (watchlist + holdings)
  scanner.py daily --all           ...across every liquid listed share (needs pkdata.py universe + psx --all)
  scanner.py orb                   during the session: opening-range breakouts on the shortlist
  scanner.py orb --at 10:30        ...as of a time (replays use --now "YYYY-MM-DD HH:MM")
  scanner.py movers                right now: biggest gainers, losers and volume (one live request)

Daily setups (on closing prices; PSX's free end-of-day series has no daily high/low):
  breakout     closed above its highest close of the previous 20 sessions, on 1.5x average volume
  flag         rose 8%+ over ten sessions, then rested in a tight band (5 sessions, under 4% wide)
  bounce       RSI(14) was under 30 and today closed higher: an oversold turn
  high52       within 2% of its 52-week high close
  gap          opened 3%+ above the previous close
  surge        traded 3x its average volume and closed 2%+ higher
Each comes with a trigger (the price that would confirm it) and a stop idea (the price that would
prove it wrong), for psx-entry and psx-exit. With --all, shares trading less than
scan_min_value_traded rupees a day are left out: day trading needs buyers and sellers.

Opening-range breakout: the high and low of the first orb_minutes of the session (09:32 Monday-
Thursday, 09:17 Friday). A 5-minute close above the range high is a breakout. One intraday request
per share, one a second, so the shortlist is kept short (--max 30).

Writes <home>/trader/setups.json. Nothing here is advice or an order.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402
import psxinfo as P  # noqa: E402


def rsi(closes, n=14, end=None):
    end = len(closes) - 1 if end is None else end
    if end < n:
        return None
    gains = losses = 0.0
    for i in range(end - n + 1, end + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def avg_move(closes, n=14):
    moves = [abs(closes[i] - closes[i - 1]) for i in range(max(1, len(closes) - n), len(closes))]
    return sum(moves) / len(moves) if moves else 0.0


def daily_setups(rows):
    """Setups that fired on the last row of end-of-day prices."""
    if len(rows) < 30:
        return []
    c = [r["close"] for r in rows]
    v = [r.get("volume") or 0 for r in rows]
    o = [r.get("open") or r["close"] for r in rows]
    last, prev = c[-1], c[-2]
    avgv = sum(v[-21:-1]) / 20.0 if len(v) > 21 else 0
    vr = v[-1] / avgv if avgv else None
    mv = avg_move(c)
    out = []
    hi20 = max(c[-21:-1])
    if last > hi20 and vr and vr >= 1.5:
        out.append({"setup": "breakout", "trigger": round(last, 2), "stop": round(max(hi20 - mv, last * 0.9), 2),
                    "why": "closed %.2f above its 20-day high close %.2f on %.1fx volume" % (last - hi20, hi20, vr)})
    if len(c) > 16:
        run = c[-6] / c[-16] - 1
        band = c[-5:]
        width = max(band) / min(band) - 1
        if run >= 0.08 and width <= 0.04 and min(band) > c[-16] + 0.5 * (c[-6] - c[-16]):
            out.append({"setup": "flag", "trigger": round(max(band), 2), "stop": round(min(band), 2),
                        "why": "up %.0f%% in ten sessions, then a %.1f%%-wide rest for five" % (100 * run, 100 * width)})
    r_prev = rsi(c, 14, len(c) - 2)
    if r_prev is not None and r_prev < 30 and last > prev:
        out.append({"setup": "bounce", "trigger": round(last, 2), "stop": round(min(c[-5:]), 2),
                    "why": "RSI(14) was %.0f yesterday and today closed higher" % r_prev})
    if len(c) >= 252:
        h52 = max(c[-252:])
        if last >= 0.98 * h52:
            out.append({"setup": "high52", "trigger": round(h52, 2), "stop": round(last - 2 * mv, 2),
                        "why": "%.1f%% from its 52-week high close %.2f" % (100 * (h52 / last - 1), h52)})
    if prev and o[-1] >= prev * 1.03:
        out.append({"setup": "gap", "trigger": round(o[-1], 2), "stop": round(prev, 2),
                    "why": "opened %.1f%% above the previous close" % (100 * (o[-1] / prev - 1))})
    if vr and vr >= 3 and last >= prev * 1.02:
        out.append({"setup": "surge", "trigger": round(last, 2), "stop": round(prev, 2),
                    "why": "%.1fx its average volume, closed %.1f%% higher" % (vr, 100 * (last / prev - 1))})
    for s in out:
        s.update(close=last, date=rows[-1]["date"], volume_ratio=round(vr, 2) if vr else None,
                 value_traded=round(sum(c[i] * v[i] for i in range(-min(60, len(c)), 0)) / min(60, len(c))),
                 avg_move=round(mv, 2))
    return out


def shortlist(h, cfg, symbols=None, all_=False):
    import freshness as F
    return F.scope(h, cfg, symbols, all_)


def cmd_daily(a, h, cfg):
    import freshness as F
    syms = shortlist(h, cfg, a.symbols, a.all)
    F.decide(a, h, cfg, syms, payouts=False)
    uni = P.load_universe(h)
    floor = desk.setting(cfg, "scan_min_value_traded") if a.all else 0
    found, skipped = [], 0
    for s in syms:
        p = C.price_path(h, s)
        if not os.path.exists(p) or s == cfg["benchmark"].upper():
            continue
        for st in daily_setups(C.read_prices(p)):
            if st["value_traded"] < floor:
                skipped += 1
                continue
            lo, hi = C.circuit_band(st["close"], cfg)
            st.update(symbol=s, shariah=(uni.get(s) or {}).get("shariah"),
                      sector=(P.load_company(h, s) or {}).get("sector") or (uni.get(s) or {}).get("sector"),
                      band=[lo, hi])
            found.append(st)
    order = {"breakout": 0, "flag": 1, "gap": 2, "surge": 3, "high52": 4, "bounce": 5}
    found.sort(key=lambda x: (order.get(x["setup"], 9), -(x.get("volume_ratio") or 0)))
    res = {"mode": "daily", "made": desk.now(a.now).isoformat(timespec="minutes"), "scanned": len(syms),
           "setups": found[:a.max]}
    desk.write(h, "setups.json", res)
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print("Daily setups: %d found in %d shares%s." % (len(found), len(syms),
                                                     " (%d too thinly traded left out)" % skipped if skipped else ""))
    if found:
        print(C.md_table(["Stock", "Setup", "Close", "Trigger", "Stop idea", "Volume x", "Today's band", "Why"],
                         [[x["symbol"] + (" ☪" if x.get("shariah") else ""), x["setup"], "%.2f" % x["close"],
                           "%.2f" % x["trigger"], "%.2f" % x["stop"], x.get("volume_ratio") or "",
                           "%.2f-%.2f" % tuple(x["band"]), x["why"]] for x in found[:a.max]]))
        print("Next: psx-news on the names you like, then psx-entry to wait for the trigger and psx-exit for the plan.")
    print(desk.DISCLAIMER)
    return 0


def orb_status(bars, minutes, at=None):
    """Opening-range state as of `at` (a datetime): range, last close, and whether it broke out."""
    import intraday as I
    if at is not None:
        bars = [b for b in bars if dt.datetime.fromisoformat(b["dt"]) + dt.timedelta(minutes=5) <= at]
    orr = I.opening_range(bars, minutes)
    if not orr or not bars:
        return None
    first = dt.datetime.fromisoformat(bars[0]["dt"]).date()
    done = C.sessions(first)[0][0] + dt.timedelta(minutes=minutes)
    after = [b for b in bars if dt.datetime.fromisoformat(b["dt"]) >= done]
    brk = next((b for b in after if b["close"] > orr["high"]), None)
    last = bars[-1]["close"]
    return {"or_high": orr["high"], "or_low": orr["low"], "or_mid": round((orr["high"] + orr["low"]) / 2, 2),
            "range_done": orr["ends"], "complete": bool(after), "last": last, "last_time": bars[-1]["t"],
            "broke_out": bool(brk), "breakout_bar": brk["t"] if brk else None,
            "above_by_pct": round(100 * (last / orr["high"] - 1), 2) if orr["high"] else None}


def cmd_orb(a, h, cfg):
    import intraday as I
    now = desk.now(a.now)
    at = now.replace(hour=int(a.at[:2]), minute=int(a.at[3:])) if a.at else now
    minutes = int(desk.setting(cfg, "orb_minutes"))
    prev = desk.read(h, "setups.json", {}) or {}
    syms = [s.upper() for s in a.symbols] or ([x["symbol"] for x in prev.get("setups", [])] if prev.get("mode") == "daily"
                                              else []) or shortlist(h, cfg)
    syms = list(dict.fromkeys(syms))[:a.max]
    rows, failed = [], []
    for s in syms:
        try:
            ff = None
            if a.from_dir:
                ff = os.path.join(a.from_dir, "%s.json" % s)
                if not os.path.exists(ff):
                    continue
            ticks = I.get(h, s, at.date().isoformat(), refresh=not a.cached, from_file=ff)
        except Exception as e:  # noqa: BLE001
            failed.append("%s (%s)" % (s, str(e)[:60]))
            continue
        st = orb_status(I.to_bars(ticks, 5), minutes, at)
        if st:
            st["symbol"] = s
            rows.append(st)
    hits = [r for r in rows if r["broke_out"]]
    hits.sort(key=lambda r: -(r["above_by_pct"] or 0))
    res = {"mode": "orb", "made": now.isoformat(timespec="minutes"), "as_of": at.strftime("%H:%M"),
           "orb_minutes": minutes, "checked": len(rows),
           "setups": [dict(r, setup="orb", trigger=r["or_high"], stop=r["or_mid"]) for r in hits]}
    desk.write(h, "setups.json", res)
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print("Opening-range breakouts as of %s (range = first %d minutes): %d of %d shares checked." % (
        res["as_of"], minutes, len(hits), len(rows)))
    if rows:
        print(C.md_table(["Stock", "Range", "Last", "At", "Broke out", "Above range"],
                         [[r["symbol"], "%.2f-%.2f" % (r["or_low"], r["or_high"]), "%.2f" % r["last"], r["last_time"],
                           ("yes, %s bar" % r["breakout_bar"]) if r["broke_out"] else ("not yet" if r["complete"] else "range still forming"),
                           "%+.2f%%" % r["above_by_pct"] if r["above_by_pct"] is not None else ""] for r in
                          sorted(rows, key=lambda r: -(r["above_by_pct"] or -99))]))
    if failed:
        print("No intraday data for: " + ", ".join(failed))
    print(desk.DISCLAIMER)
    return 0


def cmd_movers(a, h, cfg):
    import freshness as F
    try:
        snap = F.fetch_live(h) if not a.from_file else None
    except Exception as e:  # noqa: BLE001
        sys.exit("live prices failed (%s)" % e)
    if a.from_file:
        with open(a.from_file, encoding="utf-8", errors="replace") as f:
            snap = {"fetched": desk.now(a.now).strftime("%Y-%m-%d %H:%M:%S"), "quotes": F.parse_market_watch(f.read())}
    q = snap["quotes"]
    liquid = {s: x for s, x in q.items() if (x.get("volume") or 0) * (x.get("current") or 0) >= a.min_value}
    def top(key, rev=True):
        return sorted(liquid.items(), key=lambda kv: (kv[1].get(key) or 0), reverse=rev)[:a.max]
    res = {"mode": "movers", "made": snap["fetched"], "gainers": top("change_pct"), "losers": top("change_pct", False),
           "volume": top("volume")}
    desk.write(h, "setups.json", dict(res, setups=[dict(x, symbol=s, setup="mover", trigger=x["current"]) for s, x in res["gainers"]]))
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print("PSX movers at %s (shares trading at least Rs %s today)" % (snap["fetched"], "{:,.0f}".format(a.min_value)))
    for title, rows in (("GAINERS", res["gainers"]), ("LOSERS", res["losers"]), ("MOST TRADED", res["volume"])):
        print("\n" + title)
        print(C.md_table(["Stock", "Price", "Change", "Volume", "Note"],
                         [[s, "%.2f" % x["current"], "%+.2f%%" % (x.get("change_pct") or 0), "{:,.0f}".format(x.get("volume") or 0),
                           _band_note(x, cfg)] for s, x in rows]))
    print("\n" + desk.DISCLAIMER)
    return 0


MOVERS_MAX = 10          # top N gainers, losers and most traded
MOVERS_MIN_VALUE = 5e6   # rupees traded today; thinner shares can jump 10% on a few hundred shares


def _band_note(x, cfg):
    if not x.get("ldcp"):
        return ""
    lo, hi = C.circuit_band(x["ldcp"], cfg)
    if x["current"] >= hi - 0.005:
        return "at the upper price limit: few sellers"
    if x["current"] <= lo + 0.005:
        return "at the lower price limit: few buyers"
    return ""


def main(argv=None):
    import freshness as F
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("daily")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--max", type=int, default=25)
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    F.add_args(p)
    p = sub.add_parser("orb")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--at", help="HH:MM, Pakistan time")
    p.add_argument("--now")
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--cached", action="store_true", help="use intraday data already on file, no download")
    p.add_argument("--from-dir", help="a folder of saved intraday responses, SYMBOL.json each")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("movers")
    p.add_argument("--max", type=int, default=MOVERS_MAX)
    p.add_argument("--min-value", type=float, default=MOVERS_MIN_VALUE, help="rupees traded today (default 5 million)")
    p.add_argument("--from-file")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"daily": cmd_daily, "orb": cmd_orb, "movers": cmd_movers}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
