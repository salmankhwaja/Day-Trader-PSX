"""Build the dashboard's sample data: a made-up PSX market, made-up MUFAP funds, a sample
portfolio and a paper account, so anyone can try the dashboard (GitHub Pages included)
before loading their own data.

    python3 tools/make_sample.py                 # writes psx-mufap/dashboard/sample-data.json
    python3 tools/make_sample.py --out FILE.json

Every company, fund, price and index level here is invented (deterministic random walks).
Real PSX data never goes in this repo: PSX restricts redistribution of its market data.
The sample is built with the same tools as real data (pkdata, portfolio, paper, dashboard),
so it always has the same shape as your own data.json.
"""
import argparse
import contextlib
import datetime as dt
import io
import json
import math
import os
import random
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "psx-mufap", "scripts"))

import common as C  # noqa: E402
import dashboard  # noqa: E402
import paper  # noqa: E402
import pkdata  # noqa: E402
import portfolio as PF  # noqa: E402
import psxinfo as P  # noqa: E402

END = dt.date(2026, 10, 30)   # last sample session; bump it to refresh the sample
SESSIONS = 520
OUT = os.path.join(ROOT, "psx-mufap", "dashboard", "sample-data.json")
NOTE = "Every company, fund, price and index level here is made up."

# symbol: (name, sector, Shariah, start price, daily drift, daily volatility, P/E, cash dividend %)
# Symbols start with Z and names say "Sample" so nobody mistakes them for listed companies.
SHARES = {
    "ZCEMA": ("Sample Cement A Ltd", "CEMENT", True, 180, 0.0011, 0.019, 7.5, 40),
    "ZCEMB": ("Sample Cement B Ltd", "CEMENT", True, 95, 0.0004, 0.023, 6.1, 0),
    "ZCEMC": ("Sample Cement C Ltd", "CEMENT", False, 40, -0.0006, 0.026, 11.0, 0),
    "ZBNKA": ("Sample Bank A Ltd", "COMMERCIAL BANKS", False, 150, 0.0009, 0.014, 4.2, 180),
    "ZBNKB": ("Sample Islamic Bank Ltd", "COMMERCIAL BANKS", True, 210, 0.0013, 0.015, 5.0, 150),
    "ZBNKC": ("Sample Bank C Ltd", "COMMERCIAL BANKS", False, 30, -0.0003, 0.017, 3.1, 25),
    "ZOILA": ("Sample Exploration A Ltd", "OIL & GAS EXPLORATION COMPANIES", True, 120, 0.0006, 0.016, 5.4, 90),
    "ZOILB": ("Sample Petroleum B Ltd", "OIL & GAS EXPLORATION COMPANIES", True, 420, 0.0002, 0.015, 6.3, 300),
    "ZOMCA": ("Sample Fuels Marketing Ltd", "OIL & GAS MARKETING COMPANIES", True, 260, -0.0004, 0.018, 8.0, 60),
    "ZFERA": ("Sample Fertilizer A Ltd", "FERTILIZER", True, 140, 0.0010, 0.011, 7.0, 120),
    "ZFERB": ("Sample Fertilizer B Ltd", "FERTILIZER", True, 75, 0.0005, 0.012, 6.6, 70),
    "ZPWRA": ("Sample Power A Ltd", "POWER GENERATION & DISTRIBUTION", True, 110, 0.0008, 0.013, 4.9, 100),
    "ZPWRB": ("Sample Power B Ltd", "POWER GENERATION & DISTRIBUTION", False, 25, -0.0009, 0.021, 2.8, 0),
    "ZTECA": ("Sample Technologies A Ltd", "TECHNOLOGY & COMMUNICATION", True, 380, 0.0015, 0.024, 14.0, 20),
    "ZTECB": ("Sample Software B Ltd", "TECHNOLOGY & COMMUNICATION", True, 60, -0.0012, 0.028, 19.0, 0),
    "ZAUTA": ("Sample Motors Ltd", "AUTOMOBILE ASSEMBLER", True, 520, 0.0007, 0.017, 9.0, 250),
    "ZFOOD": ("Sample Foods Ltd", "FOOD & PERSONAL CARE PRODUCTS", True, 90, 0.0003, 0.013, 12.0, 35),
    "ZTEXA": ("Sample Textile Mills Ltd", "TEXTILE COMPOSITE", True, 70, -0.0002, 0.016, 8.5, 30),
}
INDEX = ("KSE100", 70000, 0.0007, 0.010)   # the sample's own made-up index, shown as the benchmark
WATCHLIST = ["ZCEMA", "ZBNKB", "ZOILA", "ZFERA", "ZTECA", "ZPWRA", "ZAUTA", "ZFOOD"]

# MUFAP-style categories: (heading as on MUFAP, funds: (name, NAV, YTD, 30D, 90D, 1Y, 3Y))
FUNDS = [
    ("Money Market (Annualized Return )", [
        ("Sample Cash Fund", 10.6201, 10.8, 10.9, 10.7, 10.7, 16.8),
        ("Sample Money Market Fund", 104.5512, 10.6, 10.5, 10.6, 10.6, 16.4),
        ("Sample Daily Income Fund", 53.9110, 11.0, 10.8, 11.0, 11.0, 16.7)]),
    ("Shariah Compliant Money Market (Annualized Return )", [
        ("Sample Islamic Cash Fund", 101.2234, 10.4, 10.3, 10.5, 10.4, 16.2),
        ("Sample Islamic Money Market Fund", 10.4417, 10.2, 10.4, 10.2, 10.3, 15.9)]),
    ("Income (Annualized Return )", [
        ("Sample Income Fund", 11.2205, 11.6, 11.1, 11.9, 12.4, 17.1),
        ("Sample Government Securities Fund", 108.8810, 11.2, 10.7, 11.4, 12.0, 16.6)]),
    ("Equity (Absolute Return )", [
        ("Sample Stock Fund", 33.4120, 18.2, 2.1, 6.4, 31.5, 140.2),
        ("Sample Growth Fund", 212.0045, 14.9, 1.4, 4.9, 26.8, 118.7),
        ("Sample Value Fund", 18.7731, 9.1, -1.2, 2.2, 15.3, 88.4)]),
    ("Shariah Compliant Equity (Absolute Return )", [
        ("Sample Islamic Stock Fund", 25.9008, 16.4, 1.8, 5.7, 29.1, 131.6),
        ("Sample Islamic Energy Fund", 14.3315, 21.7, 3.4, 9.8, 36.2, 155.0)]),
]

HEAD = ("| Sector | Category | Fund Name | Rating | Benchmark | Validity Date | NAV | YTD | MTD | 1 Day | 15 Days | "
        "30 Days | 90 Days | 180 Days | 270 Days | 365 Days | 2 Years | 3 Years |")


def sessions():
    days, d = [], END
    while len(days) < SESSIONS:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return days[::-1]


def walk(seed, start, drift, vol, days):
    """Portal-format EOD rows, newest first: [unix time, close, volume, open]."""
    rnd = random.Random(seed)
    px, rows = float(start), []
    for d in days:
        op = px * (1 + rnd.gauss(0, vol / 3))
        px = max(1.0, px * math.exp(drift + rnd.gauss(0, vol)))
        ts = int(dt.datetime(d.year, d.month, d.day, 10, 30, tzinfo=dt.timezone.utc).timestamp())
        rows.append([ts, round(px, 2), rnd.randint(60000, 2500000), round(op, 2)])
    return {"status": 1, "message": "", "data": rows[::-1]}


def r(v):
    return "(%.2f)" % -v if v < 0 else "%.2f" % v


def mufap_page():
    when = END.strftime("%b %d, %Y")
    out = ["## NAV Returns Performance Summary Report", "", "Report Time: 5:00:00 PMReport Date: " + when, "", "",
           HEAD.replace("| Category ", ""), "|" + " --- |" * 17]
    for heading, funds in FUNDS:
        out.append("| %s |" % heading)
        out.append(HEAD)
        for name, nav, ytd, d30, d90, y1, y3 in funds:
            out.append("| Open-End Funds | [%s](https://example.com/sample) | AA(f) | N/A | %s | %.4f | %s | %s | %s | %s | %s | %s | "
                       "%s | %s | %s | %s | %s |" % (name, when, nav, r(ytd), r(d30 / 2), r(d30 / 30), r(d30 / 2), r(d30), r(d90),
                                                     r(d90 * 1.6), r(y1 * 0.7), r(y1), r(y1 * 1.7), r(y3)))
    return "\n".join(out) + "\n"


def quiet(fn, argv):
    with contextlib.redirect_stdout(io.StringIO()):
        rc = fn(argv)
    if rc:
        raise SystemExit("sample build step failed: %s" % " ".join(argv))


def build(out=OUT):
    h = tempfile.mkdtemp(prefix="pkm-sample-")
    src = tempfile.mkdtemp(prefix="pkm-sample-src-")
    try:
        days = sessions()
        with open(os.path.join(h, "config.json"), "w") as f:
            json.dump({"watchlist": WATCHLIST, "benchmark": "KSE100", "min_avg_volume": 10000,
                       "risk_profile": "moderate"}, f)
        uni = {}
        for k, (sym, (name, sector, shariah, px, drift, vol, pe, cash)) in enumerate(SHARES.items()):
            uni[sym] = {"name": name, "price": None, "shares_m": 50 + 10 * k, "mcap_m": 5000 + 900 * k,
                        "tags": [], "shariah": shariah}
            pays = []
            if cash:   # last year's dividend, plus one announced for the weeks after END
                last = END - dt.timedelta(days=300 - 9 * k)
                nxt = END + dt.timedelta(days=6 + 3 * k)
                for d, kind in ((last, "final"), (nxt, "interim i")):
                    pays.append({"announced": (d - dt.timedelta(days=14)).isoformat(), "period": "30/06/2026(YR)",
                                 "details": "%d%%(%s) (D)" % (cash, "F" if kind == "final" else "i"),
                                 "bc_from": d.isoformat(), "bc_to": (d + dt.timedelta(days=2)).isoformat(),
                                 "cash_pct": float(cash), "bonus_pct": 0.0, "right_pct": 0.0, "kind": kind})
            P.save_company(h, {"symbol": sym, "fetched": END.isoformat(), "name": name, "tags": [], "sector": sector,
                               "price": None, "pe": pe, "payouts": pays})
            path = os.path.join(src, sym + ".json")
            with open(path, "w") as f:
                json.dump(walk(1000 + k, px, drift, vol, days), f)
            quiet(pkdata.main, ["--home", h, "psx", sym, "--from-file", path])
        with open(os.path.join(h, "universe.json"), "w") as f:
            json.dump(uni, f)
        path = os.path.join(src, "KSE100.json")
        with open(path, "w") as f:
            json.dump(walk(999, *INDEX[1:], days), f)
        quiet(pkdata.main, ["--home", h, "psx", "KSE100", "--from-file", path])
        path = os.path.join(src, "mufap.md")
        with open(path, "w") as f:
            f.write(mufap_page())
        quiet(pkdata.main, ["--home", h, "mufap", "--from-file", path])

        # A sample real-money portfolio: some green, some red, one past its stop, one too big.
        close = {s: {r["date"]: r["close"] for r in C.read_prices(C.price_path(h, s))} for s in SHARES}

        def px(sym, ago):
            return close[sym][days[-1 - ago].isoformat()]

        quiet(PF.main, ["--home", h, "broker", "add", "Finqalab", "--preset", "finqalab", "--default"])
        quiet(PF.main, ["--home", h, "cash", "deposit", "1600000", "--date", days[-260].isoformat(), "--note", "sample"])
        # Picked from what the made-up market did: a winner grown too big (TRIM), steady holds,
        # one past its stop (SELL), and one share bought twice (one purchase green, one red).
        for sym, qty, ago, t in (("ZBNKB", 1500, 240, "10:12"), ("ZTECA", 120, 200, "11:40"), ("ZFOOD", 800, 160, "13:05"),
                                 ("ZOILA", 700, 150, "10:30"), ("ZCEMB", 500, 230, "14:10"), ("ZCEMB", 300, 30, "12:20"),
                                 ("ZBNKA", 900, 260, "10:55")):
            quiet(PF.main, ["--home", h, "buy", sym, str(qty), "%.2f" % px(sym, ago), "--date", days[-1 - ago].isoformat(),
                            "--time", t, "--note", "sample"])
        quiet(PF.main, ["--home", h, "sell", "ZOILA", "300", "%.2f" % px("ZOILA", 40), "--date", days[-41].isoformat(),
                        "--time", "15:05", "--note", "sample"])
        quiet(PF.main, ["--home", h, "fund-buy", "Sample Cash Fund", "100000", "--nav", "10.21",
                        "--date", days[-120].isoformat(), "--note", "sample"])

        # A paper account opened 120 sessions ago, with a daily value history for its chart.
        quiet(paper.main, ["--home", h, "init", "--cash", "1000000"])
        start = days[-120]
        for sym, qty in (("ZFERA", 1500), ("ZTECA", 400), ("ZAUTA", 250), ("ZPWRA", 1200)):
            quiet(paper.main, ["--home", h, "buy", sym, str(qty), "--price", "%.2f" % px(sym, 119), "--note", "sample"])
        left = paper.load(h)["cash"]
        quiet(paper.main, ["--home", h, "invest", "Sample Money Market Fund", "%d" % int(left * 0.6)])
        pf = paper.load(h)
        pf["created"] = start.isoformat() + "T09:30:00"
        for t in pf["trades"]:
            t["date"] = start.isoformat()
        for pos in pf["positions"].values():
            pos["opened"] = start.isoformat()
        bench = {r["date"]: r["close"] for r in C.read_prices(C.price_path(h, "KSE100"))}
        marks = []
        for d in days[-120:]:
            ds = d.isoformat()
            v = pf["cash"] + sum(p["qty"] * close[s][ds] for s, p in pf["positions"].items() if p["kind"] == "stock")
            v += sum(p["cost"] for p in pf["positions"].values() if p["kind"] != "stock")
            marks.append({"date": ds, "value": round(v, 2), "benchmark": bench.get(ds)})
        pf["marks"] = marks
        paper.save(h, pf)

        os.environ["PKM_VIEW"] = "table"
        quiet(PF.main, ["--home", h, "advise", "--no-fetch", "--all"])   # holdings verdicts, buy ideas, tickets
        data = dashboard.build_data(h, C.load_config(h))
        data["sample"] = {"note": NOTE, "as_of": END.isoformat(), "how": "python3 tools/make_sample.py"}
        data["generated"] = END.isoformat() + " 17:00"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), default=str)
        return data
    finally:
        shutil.rmtree(h, ignore_errors=True)
        shutil.rmtree(src, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    d = build(a.out)
    print("wrote %s (%.0f KB): %d sample shares, %d fund categories, %s" % (
        os.path.relpath(a.out, ROOT), os.path.getsize(a.out) / 1024, len(d["stocks"]),
        len((d.get("funds") or {}).get("categories") or {}), NOTE))
