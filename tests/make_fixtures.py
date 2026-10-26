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
if __name__ == "__main__":
    os.makedirs(HERE, exist_ok=True)
    for sym, args in SPEC.items():
        with open(os.path.join(HERE, "psx-%s.json" % sym), "w") as f:
            json.dump(series(*args), f)
    print("wrote", len(SPEC), "fixtures")
