"""Regenerate the synthetic PSX fixtures (deterministic). Real PSX data is not committed:
PSX restricts redistribution of its market data."""
import json, math, os, random, datetime as dt

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

def series(seed, start_px, drift, vol, n=600):
    rnd = random.Random(seed)
    d = dt.date(2024, 5, 1)
    px, rows = start_px, []
    while len(rows) < n:
        d += dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        op = px * (1 + rnd.gauss(0, vol / 3))
        px = max(1.0, px * math.exp(drift + rnd.gauss(0, vol)))
        # PSX EOD rows: [unix_time (UTC, session close ~10:30 UTC), close, volume, open]
        ts = int(dt.datetime(d.year, d.month, d.day, 10, 30, tzinfo=dt.timezone.utc).timestamp())
        rows.append([ts, round(px, 2), rnd.randint(10000, 900000), round(op, 2)])
    return {"status": 1, "message": "", "data": rows[::-1]}  # newest first, like the portal

SPEC = {"UPCO": (1, 100, 0.0012, 0.018), "DOWNCO": (2, 80, -0.0008, 0.02),
        "FLATCO": (3, 50, 0.0, 0.012), "WILDCO": (4, 30, 0.0006, 0.035),
        "KSE100": (5, 70000, 0.0005, 0.01)}
# A wider synthetic market for --all, sector, Shariah and proposal tests (900 sessions each).
SECTORS = ["CEMENT", "COMMERCIAL BANKS", "OIL & GAS EXPLORATION COMPANIES", "TECHNOLOGY & COMMUNICATION"]
MARKET = {}
for k in range(12):
    MARKET["SYN%02d" % k] = (100 + k, 20 + 7 * k, (k - 4) * 0.0004, 0.012 + 0.002 * (k % 4))


def universe_and_companies():
    uni, comps = {}, {}
    for k, sym in enumerate(sorted(MARKET)):
        sector = SECTORS[k % 4]
        uni[sym] = {"name": "Synthetic %s Ltd (not real)" % sym, "price": None, "shares_m": 100,
                    "mcap_m": 1000 + k, "tags": [], "shariah": k % 3 != 0}
        pays = [{"announced": "2026-%02d-10" % (1 + (k % 6)), "period": "31/12/2025(HYR)",
                 "details": "%d%%(ii) (D)" % (10 + 5 * k), "bc_from": "2026-%02d-20" % (1 + (k % 6)),
                 "bc_to": "2026-%02d-22" % (1 + (k % 6)), "cash_pct": 10.0 + 5 * k,
                 "bonus_pct": 0.0, "right_pct": 0.0, "kind": "interim ii"}]
        comps[sym] = {"symbol": sym, "fetched": "2026-10-26", "name": uni[sym]["name"], "tags": [],
                      "sector": sector, "price": None, "pe": 5.0 + k, "payouts": pays}
    return uni, comps


if __name__ == "__main__":
    os.makedirs(HERE, exist_ok=True)
    for sym, args in SPEC.items():
        with open(os.path.join(HERE, "psx-%s.json" % sym), "w") as f:
            json.dump(series(*args), f)
    for sym, args in MARKET.items():
        with open(os.path.join(HERE, "psx-%s.json" % sym), "w") as f:
            json.dump(series(*args, n=900), f)
    uni, comps = universe_and_companies()
    with open(os.path.join(HERE, "synthetic-universe.json"), "w") as f:
        json.dump({"universe": uni, "companies": comps}, f, indent=0)
    print("wrote", len(SPEC) + len(MARKET), "price fixtures and the synthetic universe")
