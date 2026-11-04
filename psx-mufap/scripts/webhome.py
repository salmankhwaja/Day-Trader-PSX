#!/usr/bin/env python3
"""A pkmarket data folder built from the website's price feed (standard library only).

The GitHub Action (tools/web_feed.py) and the website's in-browser Python (webrun.py, run by Pyodide)
both call make_home(): the feed to compute its summary with the same code as the command line, the
website so every pkm.py tool runs on the prices it has already decrypted.

  months  {"YYYY-MM": {"month", "syms": [...], "days": {date: {"c": [...], "v": [...]}}}}
  meta    the feed's meta.enc.json: shares, companies (name, sector, P/E, payouts, announcements,
          financials), payouts, mufap {date, funds}, navs {fund: {date: nav}}
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import pkdata  # noqa: E402
import psxinfo as P  # noqa: E402

INDEX = "KSE100"


def rows_by_symbol(months):
    """Monthly feed files -> {symbol: [{date, open, close, volume}]}, oldest first."""
    out = {}
    for m in sorted(months.values(), key=lambda m: m["month"]):
        for day in sorted(m["days"]):
            d = m["days"][day]
            for i, s in enumerate(m["syms"]):
                if i < len(d["c"]) and d["c"][i] is not None:
                    v = d.get("v") or []
                    out.setdefault(s, []).append({"date": day, "open": d["c"][i], "close": d["c"][i],
                                                  "volume": (v[i] if i < len(v) else 0) or 0})
    return out


def make_home(h, months, meta, config=None):
    """Write prices, the universe, company pages, payouts and MUFAP into data folder `h`.
    `config` (a dict) becomes config.json when given and none is there yet."""
    os.makedirs(h, exist_ok=True)
    cpath = os.path.join(h, "config.json")
    if config is not None and not os.path.exists(cpath):
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=1)
    for s, rows in rows_by_symbol(months).items():
        C.write_prices(C.price_path(h, s), rows)
    shares, comps = meta.get("shares", {}), meta.get("companies", {})
    uni = {s: {"name": (comps.get(s) or {}).get("name") or v.get("name"), "price": None, "shares_m": None,
               "mcap_m": None, "tags": (comps.get(s) or {}).get("tags") or [], "shariah": bool(v.get("shariah"))}
           for s, v in shares.items() if s != INDEX}
    with open(os.path.join(h, "universe.json"), "w", encoding="utf-8") as f:
        json.dump(uni, f)
    for s, v in shares.items():
        c = dict(comps.get(s) or {})
        c.update(symbol=s, name=c.get("name") or v.get("name"), sector=c.get("sector") or v.get("sector"))
        c.setdefault("payouts", [])
        P.save_company(h, c)
    with open(os.path.join(h, "payouts.json"), "w", encoding="utf-8") as f:
        json.dump(meta.get("payouts") or [], f)
    mf = meta.get("mufap")
    if mf and mf.get("funds"):
        pkdata.save_mufap(h, mf["date"], mf["funds"])
        hist = os.path.join(h, "mufap", "nav_history.csv")   # the NAV history save_mufap keeps
        cat = {f["fund"]: f["category"] for f in mf["funds"]}
        rows = [(d, name, cat.get(name, ""), nav) for name, hh in (meta.get("navs") or {}).items() for d, nav in hh.items()]
        if rows:
            with open(hist, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "fund", "category", "nav"])
                for r in sorted(rows):
                    w.writerow(r)
    return h
