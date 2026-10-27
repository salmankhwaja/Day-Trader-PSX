#!/usr/bin/env python3
"""Today's trades for a PSX share, minute by minute: the data the day-trading skills watch.

  intraday.py OGDC                       today's 5-minute bars (fetched, then cached for the day)
  intraday.py OGDC --minutes 1           1-minute bars
  intraday.py OGDC --from-file int.json  a response you saved yourself
  intraday.py OGDC --date 2026-10-23     a day cached earlier

Source: the PSX Data Portal's intraday series, https://dps.psx.com.pk/timeseries/int/<SYMBOL>, the
one its own 1-day chart uses (rows of [unix time, price, volume]). Like the end-of-day series it
needs the portal's session key, which common.http_get sends. It covers today only, so each day
that is fetched is kept in <home>/intraday/<date>/<SYMBOL>.json: after a few weeks of use the
time machine can replay intraday sessions from those days.

Times are Pakistan time. Bars are built from the trades themselves; a minute with no trade has no
bar. Sessions: Monday-Thursday 09:32-15:30, Friday 09:17-12:00 and 14:32-16:30 (common.PSX_SESSIONS).
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

INT_URL = C.PSX_HOST + "/timeseries/int/%s"


def parse_ticks(text):
    """[(datetime in Pakistan time, price, volume)] oldest first, from the portal's JSON."""
    data = json.loads(text)
    rows = data.get("data") if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        try:
            ts, price = float(r[0]), float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        vol = float(r[2]) if len(r) > 2 and r[2] is not None else 0.0
        when = dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=5)
        out.append((when, price, vol))
    out.sort(key=lambda x: x[0])
    return out


def to_bars(ticks, minutes=5):
    """[{t, dt, open, high, low, close, volume}] buckets of `minutes`, aligned to each session's open."""
    bars, cur = [], None
    for when, price, vol in ticks:
        ss = C.sessions(when.date())
        start = next((a for a, b in ss if a <= when < b + dt.timedelta(minutes=1)), None)
        if start is None:  # pre-open or post-close prints: not part of the regular session
            continue
        k = int((when - start).total_seconds() // (60 * minutes))
        t0 = start + dt.timedelta(minutes=k * minutes)
        if cur is None or cur["dt"] != t0.isoformat(timespec="minutes"):
            cur = {"t": t0.strftime("%H:%M"), "dt": t0.isoformat(timespec="minutes"), "open": price,
                   "high": price, "low": price, "close": price, "volume": 0.0}
            bars.append(cur)
        cur["high"], cur["low"] = max(cur["high"], price), min(cur["low"], price)
        cur["close"] = price
        cur["volume"] += vol
    return bars


def opening_range(bars, minutes=15):
    """(high, low, the time the range is complete) over the first `minutes` of the first session."""
    if not bars:
        return None
    first = dt.datetime.fromisoformat(bars[0]["dt"])
    ss = C.sessions(first.date())
    if not ss:
        return None
    end = ss[0][0] + dt.timedelta(minutes=minutes)
    inside = [b for b in bars if dt.datetime.fromisoformat(b["dt"]) < end]
    if not inside:
        return None
    return {"high": max(b["high"] for b in inside), "low": min(b["low"] for b in inside),
            "ends": end.strftime("%H:%M"), "bars": len(inside)}


def cache_path(h, symbol, day):
    return os.path.join(h, "intraday", day, symbol.upper() + ".json")


def save(h, symbol, ticks):
    if not ticks:
        return None
    day = ticks[-1][0].date().isoformat()
    p = cache_path(h, symbol, day)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump([[w.isoformat(timespec="seconds"), pr, v] for w, pr, v in ticks], f)
    return day


def load(h, symbol, day):
    try:
        with open(cache_path(h, symbol, day), encoding="utf-8") as f:
            return [(dt.datetime.fromisoformat(w), pr, v) for w, pr, v in json.load(f)]
    except (OSError, ValueError):
        return []


def cached_days(h, symbol):
    base = os.path.join(h, "intraday")
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, symbol.upper() + ".json")))


def fetch(h, symbol, from_file=None):
    """Today's ticks, fetched (or read from a saved file) and cached."""
    if from_file:
        with open(from_file, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = C.http_get(INT_URL % symbol.upper())
    ticks = parse_ticks(text)
    save(h, symbol, ticks)
    return ticks


def get(h, symbol, day=None, refresh=True, from_file=None):
    """Ticks for `day` (default today): fetched if it's today and refresh is on, else from the cache."""
    today = C.pk_now().date().isoformat()
    day = day or today
    if from_file or (refresh and day == today):
        try:
            ticks = fetch(h, symbol, from_file)
            if ticks and (from_file or ticks[-1][0].date().isoformat() == day):
                return ticks
        except Exception:  # noqa: BLE001 -- fall back to what was cached
            if from_file:
                raise
    return load(h, symbol, day)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("symbol")
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--date", help="a day cached earlier (YYYY-MM-DD)")
    ap.add_argument("--from-file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    try:
        ticks = get(h, a.symbol, a.date, refresh=not a.date, from_file=a.from_file)
    except Exception as e:  # noqa: BLE001
        sys.exit("intraday data failed (%s). It needs the PSX portal (the tools send its session key)." % e)
    bars = to_bars(ticks, a.minutes)
    if a.json:
        print(json.dumps({"symbol": a.symbol.upper(), "bars": bars, "opening_range": opening_range(bars)}, indent=1))
        return 0
    if not bars:
        print("No trades for %s%s (market %s)." % (a.symbol.upper(), " on " + a.date if a.date else " today",
                                                  C.market_state()))
        return 0
    print("%s %s-minute bars, %s (Pakistan time)" % (a.symbol.upper(), a.minutes, bars[0]["dt"][:10]))
    print(C.md_table(["Time", "Open", "High", "Low", "Close", "Volume"],
                     [[b["t"], "%.2f" % b["open"], "%.2f" % b["high"], "%.2f" % b["low"], "%.2f" % b["close"],
                       "{:,.0f}".format(b["volume"])] for b in bars]))
    orr = opening_range(bars)
    if orr:
        print("Opening range (first 15 minutes, to %s): %.2f - %.2f" % (orr["ends"], orr["low"], orr["high"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
