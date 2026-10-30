#!/usr/bin/env python3
"""Build and serve the PSX / MUFAP dashboard.

  dashboard.py build [--all] [--days 500]          write <home>/dashboard/{index.html,app.js,theme.js,data.json}
  dashboard.py build --standalone FILE.html        one self-contained file (open it anywhere)
  dashboard.py serve [--port 8787] [--host 127.0.0.1]

The dashboard has five views:
  Overview   KSE-100, sector league table, top-ranked shares, upcoming dividends
  Screener   "Ranked": every ranked share (shares with price history on file, liquid enough);
             "All by sector": every listed share grouped by sector, with the day's change and a
             Mover column (top 10 gainers, losers and most traded, and each sector's best);
             filter by sector, Shariah, dividend yield, watchlist, holdings or movers; tick to compare
  Compare    up to 6 shares: rebased price chart, returns, risk, valuation, dividends side by side
  Portfolio  the paper account: value vs KSE-100, allocation, holdings with review actions,
             dividends received, the latest proposal
  Funds      MUFAP rankings inside each category

`build` reads only local files written by the other tools. `serve` is a small web server for
those three files: GET only, no directory listing, strict security headers. It binds to
127.0.0.1 by default.

Fetching from the dashboard is off unless you start it with `serve --allow-refresh` (or set
PKM_DASH_REFRESH=1). Then the page can ask the server to run the daily update (fetch + rebuild):
POST /api/refresh, which needs the X-PKM-Refresh header (a plain cross-site form can't send it),
a Host that is an IP address, localhost or a name in PKM_DASH_HOSTNAMES (defeats DNS rebinding),
a matching Origin, the password when one is set, and runs at most once at a time with a cool-down.
GET /api/status says whether refresh is allowed and how the last one went. The page remembers
your choice (ask each time / use stored data / fetch automatically when stale) in a cookie.

Live prices are off unless you start it with `serve --allow-live` (or PKM_DASH_LIVE=1). Then
GET /api/live (same header, Host and password rules, header X-PKM-Live) returns the PSX portal's
market watch: every share's current price, fetched at most once every 30 seconds however many
pages ask. The page polls it once a minute while the market is open and you've switched Live on. To reach it from your phone, use a private network such as Tailscale and
`--host <tailscale IP>`; any non-loopback host requires a password in PKM_DASHBOARD_PASSWORD
(HTTP Basic auth, user "pkm"). The data is PSX market data: keep it private.
"""
import argparse
import base64
import datetime as dt
import hmac
import http.server
import ipaddress
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import psxinfo as P  # noqa: E402
import paper  # noqa: E402
import propose  # noqa: E402
import rank  # noqa: E402
import portfolio as PF  # noqa: E402
import advice as A  # noqa: E402

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
         "/data.json": ("data.json", "application/json")}


def r4(x):
    return None if x is None else round(x, 4)


def build_data(h, cfg, all_=None, days=500):
    if all_ is None:
        all_ = bool(P.load_universe(h))
    ranked, bm, notes = rank.rank_stocks(h, cfg, None, "score", all_)
    watch = {s.upper() for s in cfg["watchlist"]}
    pf = paper.load(h) if os.path.exists(paper.ppath(h)) else None
    held = {k for k, v in (pf or {}).get("positions", {}).items() if v.get("kind") == "stock"}  # paper
    owned = set()
    if os.path.exists(PF.lpath(h)):
        owned = {p["symbol"] for p in PF.holdings(h, PF.load(h))}
    held_any = held | owned
    # Make sure watchlist and held names are in, even if illiquid or outside the universe.
    have = {m["symbol"] for m in ranked}
    extra = sorted((watch | held_any) - have)
    if extra:
        more, _, _ = rank.rank_stocks(h, cfg, extra, "score", False, min_volume=0)
        ranked += more

    # Shared calendar for price series: the last `days` dates seen across all series.
    series_rows = {}
    for m in ranked:
        series_rows[m["symbol"]] = C.read_prices(C.price_path(h, m["symbol"]))[-days:]
    bench = cfg["benchmark"].upper()
    if os.path.exists(C.price_path(h, bench)):
        series_rows[bench] = C.read_prices(C.price_path(h, bench))[-days:]
    cal = sorted({r["date"] for rows in series_rows.values() for r in rows})[-days:]
    idx = {d: i for i, d in enumerate(cal)}
    series = {}
    for s, rows in series_rows.items():
        arr = [None] * len(cal)
        for r in rows:
            if r["date"] in idx:
                arr[idx[r["date"]]] = r["close"]
        series[s] = arr

    stocks = []
    for m in ranked:
        d = m.get("dividends") or {}
        c = P.load_company(h, m["symbol"]) or {}
        pays = sorted(c.get("payouts") or [], key=lambda p: p.get("announced") or "", reverse=True)[:8]
        stocks.append({
            "symbol": m["symbol"], "name": m.get("name"), "sector": m.get("sector"),
            "shariah": m.get("shariah"), "tags": m.get("tags") or [], "close": m["close"],
            "last_date": m["last_date"], "watch": m["symbol"] in watch, "held": m["symbol"] in held,
            "owned": m["symbol"] in owned,
            "r1w": r4(m["1w"]), "r1m": r4(m["1m"]), "r3m": r4(m["3m"]), "r6m": r4(m["6m"]),
            "r1y": r4(m["1y"]), "ytd": r4(m["ytd"]), "vol": r4(m["vol"]), "mdd": r4(m["mdd"]),
            "sharpe": r4(m["sharpe"]), "vs_idx_3m": r4(m["vs_index_3m"]), "trend": rank.trend_label(m),
            "score": r4(m["score"]), "avg_volume": round(m["avg_volume"]), "pe": m.get("pe"),
            "mcap_m": m.get("mcap_m"), "low_52w": c.get("low_52w"), "high_52w": c.get("high_52w"),
            "div": {"yield": r4(d.get("yield_ttm")), "dps_ttm": d.get("dps_ttm"), "last": d.get("last"),
                    "last_dps": d.get("last_dps"), "upcoming": d.get("upcoming") or [],
                    "expected_next": d.get("expected_next"), "face_value": d.get("face_value")} if d else None,
            "payouts": [{k: p.get(k) for k in ("announced", "period", "details", "bc_from", "bc_to")} for p in pays],
        })

    today = dt.date.today().isoformat()
    soon = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    calendar = []
    for s in stocks:
        dv = s["div"] or {}
        for u in dv.get("upcoming") or []:
            calendar.append({"symbol": s["symbol"], "type": "announced", "date": u.get("bc_from"),
                             "details": u.get("details"), "held": s["held"] or s["owned"], "shariah": s["shariah"]})
        e = dv.get("expected_next")
        if e and today <= e["around"] <= soon:
            calendar.append({"symbol": s["symbol"], "type": "expected", "date": e["around"],
                             "details": "like last year: %s" % e.get("last_year"), "held": s["held"] or s["owned"],
                             "shariah": s["shariah"]})
    calendar.sort(key=lambda x: x["date"] or "")

    portfolio = None
    if pf:
        _, total = paper.valuation(h, cfg, pf)
        _, review = propose.review(h, cfg, 0.15)
        rv = {r["symbol"]: r for r in review}
        hold = []
        for k, pos in sorted(pf["positions"].items()):
            if pos["kind"] == "stock":
                px, asof = paper.stock_price(h, k)
                value = pos["qty"] * px if px else pos["cost"]
                info = next((s for s in stocks if s["symbol"] == k), {})
                hold.append({"kind": "stock", "symbol": k, "qty": pos["qty"], "cost": round(pos["cost"], 2),
                             "price": px, "asof": asof, "value": round(value, 2),
                             "pl": r4(value / pos["cost"] - 1) if pos["cost"] else None,
                             "sector": info.get("sector"), "shariah": info.get("shariah"),
                             "strategy": (pos.get("meta") or {}).get("strategy"),
                             "params": (pos.get("meta") or {}).get("params"), "opened": pos.get("opened"),
                             "action": rv.get(k, {}).get("action"), "why": rv.get(k, {}).get("why")})
            else:
                hold.append({"kind": "fund", "symbol": pos["fund"], "category": pos.get("category"),
                             "units": pos["units"], "cost": round(pos["cost"], 2)})
        fund_navs = {}
        try:
            _, funds = rank.fund_rows(h)
            fund_navs = {f["fund"]: f for f in funds}
        except SystemExit:
            pass
        for hh in hold:
            if hh["kind"] == "fund":
                f = fund_navs.get(hh["symbol"])
                hh["price"] = f["nav"] if f else None
                hh["value"] = round(hh["units"] * f["nav"], 2) if f else hh["cost"]
                hh["pl"] = r4(hh["value"] / hh["cost"] - 1) if hh["cost"] else None
        divs = [t for t in pf["trades"] if t.get("side") == "dividend"]
        portfolio = {"created": pf["created"], "starting_cash": pf["starting_cash"], "cash": round(pf["cash"], 2),
                     "total": round(total, 2), "return": r4(total / pf["starting_cash"] - 1),
                     "benchmark": pf.get("benchmark"), "holdings": hold, "marks": pf.get("marks", [])[-500:],
                     "dividends": divs[-50:], "trades": pf["trades"][-100:],
                     "realized": round(sum(t.get("realized", 0) for t in pf["trades"]), 2)}

    mine = None
    if os.path.exists(PF.lpath(h)):
        lg = PF.load(h)
        s = PF.summary(h, lg)
        review = A.review_holdings(h, cfg, lg, s)
        import signals as SG
        found, sg_snap = SG.lookup(h, cfg, [r["symbol"] for r in review])
        for r in review:
            A.attach_opinion(r, found.get(r["symbol"]), r.get("action"))
        rv = {r["symbol"]: r for r in review}
        info = {x["symbol"]: x for x in stocks}
        hold = []
        for p in s["holdings"]:
            r = rv.get(p["symbol"], {})
            i = info.get(p["symbol"], {})
            hold.append({"symbol": p["symbol"], "qty": p["qty"], "avg_cost": round(p["avg_cost"], 2),
                         "cost": round(p["cost"], 2), "price": p["price"], "price_date": p["price_date"],
                         "value": p["value"], "unrealised": p["unrealised"], "unrealised_pct": r4(p["unrealised_pct"]),
                         "dividends": p["dividends"], "brokers": p["brokers"], "first_buy": p["first_buy"],
                         "days_held": p["days_held"], "sector": i.get("sector"), "shariah": i.get("shariah"),
                         "action": r.get("action"), "why": r.get("why"), "notes": r.get("notes") or [],
                         "stop": r.get("stop"), "stop_source": r.get("stop_source"), "target": r.get("target"),
                         "weight": r4(r.get("weight")), "trim_qty": r.get("trim_qty"), "calc": r.get("calc"),
                         "first_buy_time": p.get("first_buy_time"), "price_source": p.get("price_source"),
                         "price_time": p.get("price_time"), "net_pl": p.get("net_pl"), "net_pl_pct": r4(p.get("net_pl_pct")),
                         "status": p.get("status"), "theirs": r.get("theirs"),
                         "lots": [{"date": l["date"], "time": l.get("time"), "qty": l["qty"], "broker": l["broker"],
                                   "unit_cost": round(l["unit_cost"], 4), "cost": l.get("cost"), "net_pl": l.get("net_pl"),
                                   "status": l.get("status")} for l in p["lots"]]})
        fees = PF.fee_table(lg)
        adv = None
        adir = os.path.join(h, "advice")
        if os.path.isdir(adir):
            files = sorted(f for f in os.listdir(adir) if f.endswith(".json"))
            if files:
                with open(os.path.join(adir, files[-1]), encoding="utf-8") as f:
                    adv = json.load(f)
        import funds as FU
        try:
            _, frev = FU.review(h)
        except SystemExit:
            frev = []
        fr = {r["fund"]: r for r in frev}
        my_funds = [dict(f, action=fr.get(f["fund"], {}).get("action"), why=fr.get(f["fund"], {}).get("why"),
                         unrealised_pct=r4(f["unrealised_pct"])) for f in s["funds"]]
        mine = {"second_opinion": sg_snap.get("updated") if sg_snap else None,
                "tickets": (adv or {}).get("tickets") or [],
                "summary": {k: s[k] for k in ("value", "cost", "unrealised", "realised", "dividends", "fees", "cash")},
                "funds": my_funds,
                "holdings": hold, "sales": s["sales"][-100:],
                "fees": [dict(v, broker=k) for k, v in sorted(fees.items())],
                "dividends": [e for e in lg["entries"] if e["type"] == "dividend"][-100:],
                "buy_ideas": (adv or {}).get("buy") or [], "advice_date": (adv or {}).get("generated"),
                "settings": {k: A.setting(cfg, k) for k in A.DEFAULTS}}

    proposal = None
    pdir = os.path.join(h, "proposals")
    if os.path.isdir(pdir):
        files = sorted(f for f in os.listdir(pdir) if f.endswith(".json"))
        if files:
            with open(os.path.join(pdir, files[-1]), encoding="utf-8") as f:
                proposal = json.load(f)

    funds = None
    try:
        fdate, frows = rank.fund_rows(h)
        by = rank.rank_funds(frows)
        funds = {"date": fdate, "categories": {
            cat: {"type": fs[0]["return_type"], "count": len(fs),
                  "median_1y": statistics.median([f["d365"] for f in fs if f["d365"] is not None])
                  if any(f["d365"] is not None for f in fs) else None,
                  "funds": [{k: f[k] for k in ("fund", "rating", "nav", "validity_date", "ytd", "d30", "d90",
                                                "d365", "y3", "score")} for f in fs[:15]]}
            for cat, fs in by.items()}}
    except SystemExit:
        pass

    import freshness
    flog = freshness.read_log(h)
    snap = None
    try:
        from pkdata import latest_mufap
        snap = latest_mufap(h)
    except Exception:
        pass
    return {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "freshness": {"prices_as_of": cal[-1] if cal else None, "last_fetch": flog.get("psx"),
                      "mufap_as_of": os.path.basename(snap)[:-4] if snap else None,
                      "mufap_fetched": flog.get("mufap")},
        "scope": "all" if all_ else "watchlist",
        "benchmark": {"symbol": bench, "metrics": {k: r4(bm[k]) for k in ("1m", "3m", "6m", "1y", "ytd", "vol", "mdd")}
                      if bm else None},
        "notes": {"illiquid_left_out": notes["illiquid"], "min_volume": notes["min_volume"],
                  "face_value_note": "Dividend per share assumes Rs 10 face value unless config.json face_values says otherwise."},
        "calendar": cal, "series": series, "stocks": stocks,
        "sectors": rank.sector_summary([dict(s, **{"1m": s["r1m"], "3m": s["r3m"], "1y": s["r1y"],
                                                   "div_yield": (s["div"] or {}).get("yield"),
                                                   "score": s["score"]}) for s in stocks]),
        "dividend_calendar": calendar, "portfolio": portfolio, "proposal": proposal, "funds": funds,
        "mine": mine,
        "risk": risk_block(h, cfg),
        "market": market_block(h, cfg, stocks),
    }


def market_block(h, cfg, stocks):
    """Every listed share, grouped by sector in the page: price, the day's change and volume, for
    the Screener's "All shares by sector" view. Sources, best first: the last market-watch snapshot
    (live.json: one request covers every share), else the last two daily closes on file, else the
    index page's price in universe.json. Sector: the ranked data, the company page, the market watch."""
    import freshness as F
    import scanner
    uni = P.load_universe(h)
    snap = F.load_live(h) or {}
    quotes = snap.get("quotes") or {}
    by = {s["symbol"]: s for s in stocks}
    rows = []
    for sym in sorted(set(uni) | set(quotes) | set(by)):
        u, x, st = uni.get(sym) or {}, quotes.get(sym) or {}, by.get(sym) or {}
        sector = st.get("sector")
        if not sector:
            sector = (P.load_company(h, sym) or {}).get("sector") or x.get("sector")
        price = change = volume = None
        src = None
        if x.get("current"):
            price, volume, src = x["current"], x.get("volume"), "market watch"
            change = x["change_pct"] / 100 if x.get("change_pct") is not None else None
        elif os.path.exists(C.price_path(h, sym)):
            last = C.read_prices(C.price_path(h, sym), live=False)[-2:]
            if last:
                price, volume, src = last[-1]["close"], last[-1].get("volume"), "close " + last[-1]["date"]
                if len(last) == 2 and last[0]["close"]:
                    change = last[-1]["close"] / last[0]["close"] - 1
        elif u.get("price"):
            price, src = u["price"], "index page"
        rows.append({"symbol": sym, "name": st.get("name") or u.get("name") or (x.get("name")),
                     "sector": (sector or "").strip().upper() or "UNCLASSIFIED",
                     "shariah": st.get("shariah") if st else u.get("shariah"),
                     "price": price, "change": r4(change), "volume": volume,
                     "value": round(price * volume) if price and volume else None, "source": src,
                     "ranked": bool(st), "score": st.get("score"), "watch": st.get("watch", False),
                     "owned": st.get("owned", False) or st.get("held", False)})
    return {"as_of": snap.get("fetched"), "rows": rows, "movers_max": scanner.MOVERS_MAX,
            "movers_min_value": scanner.MOVERS_MIN_VALUE}


def risk_block(h, cfg):
    """Profile, its key settings, portfolio risk and SIP starting values, for the Risk & SIP tab."""
    import profiles as PRF
    import risk as RK
    import sip as SP
    keys = ["risk_per_trade", "max_position_pct", "max_holdings", "cash_reserve_pct", "max_open_risk_pct",
            "stop_atr_mult", "min_stop_pct", "max_stop_pct", "target_r", "gate_max_drawdown", "gate_min_sharpe",
            "max_annual_loss_pct"]
    out = {"profile": cfg.get("risk_profile"),
           "settings": [{"key": k, "value": RK.fmt(cfg.get(k), k), "about": PRF.VARIABLES[k][1]} for k in keys],
           "allocation_target": cfg.get("allocation")}
    rates, src = SP.market_rates(h, cfg)
    alloc = cfg.get("allocation") or {}
    out["sip"] = {"rate": round(SP.blended(alloc, rates), 4) if alloc else 0.12,
                  "basis": "%s mix at %s" % (cfg.get("risk_profile"), ", ".join(
                      "%s %.1f%%" % (k.replace("_", " "), 100 * rates[k]) for k in alloc if k in rates))}
    try:
        import portfolio as PF
        out["portfolio"] = RK.portfolio_risk(h, cfg) if os.path.exists(PF.lpath(h)) else None
    except Exception:  # risk numbers are a bonus; never break the dashboard over them
        out["portfolio"] = None
    return out


def cmd_build(a, h, cfg):
    data = build_data(h, cfg, True if a.all else None, a.days)
    blob = json.dumps(data, separators=(",", ":"), default=str)
    if a.standalone:
        with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as f:
            page = f.read()
        with open(os.path.join(UI_DIR, "app.js"), encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(UI_DIR, "theme.js"), encoding="utf-8") as f:
            page = page.replace('<script src="theme.js"></script>', "<script>%s</script>" % f.read())
        inline = "<script>window.PKM_DATA=%s;</script>\n<script>%s</script>" % (
            blob.replace("</", "<\\/"), js)
        page = page.replace('<script src="app.js"></script>', inline)
        with open(a.standalone, "w", encoding="utf-8") as f:
            f.write(page)
        print("standalone dashboard: %s (%.1f MB, %d shares)" % (a.standalone, len(page) / 1e6, len(data["stocks"])))
        return 0
    out = os.path.join(h, "dashboard")
    os.makedirs(out, exist_ok=True)
    for fn in ("index.html", "app.js", "theme.js"):
        shutil.copyfile(os.path.join(UI_DIR, fn), os.path.join(out, fn))
    with open(os.path.join(out, "data.json"), "w", encoding="utf-8") as f:
        f.write(blob)
    print("dashboard built in %s: %d shares, %d dates, %.1f MB of data" % (
        out, len(data["stocks"]), len(data["calendar"]), len(blob) / 1e6))
    return 0


LIVE_CACHE = {"at": 0.0, "snap": None}
LIVE_LOCK = threading.Lock()
LIVE_TTL = 30  # seconds: PSX is asked at most twice a minute
REFRESH = {"running": False, "started": None, "finished": None, "ok": None, "last_start": 0.0, "tail": []}
REFRESH_LOCK = threading.Lock()
COOLDOWN = 120  # seconds between refreshes
HOST_RE = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[0-9.]+|localhost)(:\d+)?$")


def run_refresh(home, scope):
    """Run the daily update (fetch everything, rebuild the dashboard) in the background."""
    log = os.path.join(home, "logs")
    os.makedirs(log, exist_ok=True)
    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily.py"),
           "--home", home, "--scope", scope]
    ok = False
    out = []
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3600)
        out = p.stdout.decode("utf-8", "replace").splitlines()
        ok = p.returncode == 0
        with open(os.path.join(log, "refresh.log"), "w", encoding="utf-8") as f:  # the last run only
            f.write("\n".join(out) + "\n")
    except (OSError, subprocess.SubprocessError) as e:
        out = ["refresh failed: %s" % e]
    problems = []
    for l in out:
        l = l.strip()
        m, m2 = re.match(r"(\d+) failed:", l), re.match(r"([\w ]+?) stopped:", l)
        if m:
            problems.append("%s share price download%s failed" % (m.group(1), "" if m.group(1) == "1" else "s"))
        elif m2:
            problems.append("%s download failed" % m2.group(1))
        elif " failed:" in l and "FAILED" not in l and not l.startswith(("payouts", "mufap")):
            problems.append(l.split(" failed:")[0] + " failed")
    if not problems and any("FAILED" in l for l in out):
        problems = ["some downloads failed"]
    with REFRESH_LOCK:
        REFRESH.update(running=False, finished=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       ok=ok and not problems, tail=list(dict.fromkeys(problems))[:6])


class Handler(http.server.BaseHTTPRequestHandler):
    root = None
    password = None
    home = None
    allow_refresh = False
    allow_live = False
    scope = "watchlist"
    hostnames = ()
    server_version = "pkm"
    sys_version = ""

    def _headers(self, code, ctype=None, length=0):
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self' https://cdnjs.cloudflare.com; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                         "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def _authorized(self):
        if not self.password:
            return True
        got = self.headers.get("Authorization", "")
        want = "Basic " + base64.b64encode(("pkm:" + self.password).encode()).decode()
        return hmac.compare_digest(got.encode(), want.encode())

    def _deny_auth(self):
        self._headers(401, "text/plain", 0)
        self.send_header("WWW-Authenticate", 'Basic realm="pkm dashboard"')
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self._headers(code, "application/json", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        with REFRESH_LOCK:
            st = {k: REFRESH[k] for k in ("running", "started", "finished", "ok", "tail")}
        st["refresh"] = bool(self.allow_refresh)
        st["live"] = bool(self.allow_live)
        st["cooldown"] = max(0, int(COOLDOWN - (time.time() - REFRESH["last_start"]))) if REFRESH["last_start"] else 0
        return st

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host
        if not (HOST_RE.match(host) or name.lower() in self.hostnames):
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in ("http://" + host, "https://" + host)

    def do_GET(self):
        if not self._authorized():
            return self._deny_auth()
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/api/status":
            return self._json(200, self._status())
        if path == "/api/live":
            return self._live()
        if path not in FILES:
            self._headers(404, "text/plain", 9)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        fn, ctype = FILES[path]
        try:
            with open(os.path.join(self.root, fn), "rb") as f:
                body = f.read()
        except OSError:
            msg = b"run `dashboard.py build` first\n"
            self._headers(503, "text/plain", len(msg))
            self.end_headers()
            self.wfile.write(msg)
            return
        self._headers(200, ctype, len(body))
        self.end_headers()
        self.wfile.write(body)

    def _live(self):
        if not self.allow_live:
            return self._json(404, {"error": "live prices are off: start the server with --allow-live"})
        if self.headers.get("X-PKM-Live") != "1" or not self._host_ok():
            return self._json(403, {"error": "refused: needs the dashboard's own page on an allowed host"})
        import freshness
        with LIVE_LOCK:
            if LIVE_CACHE["snap"] is None or time.time() - LIVE_CACHE["at"] >= LIVE_TTL:
                try:
                    LIVE_CACHE["snap"] = freshness.fetch_live(self.home)
                    LIVE_CACHE["at"] = time.time()
                    LIVE_CACHE.pop("error", None)
                except Exception as e:  # noqa: BLE001 -- report, keep the last good snapshot
                    LIVE_CACHE["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
                    LIVE_CACHE["at"] = time.time()  # don't hammer PSX while it's failing
            snap, err = LIVE_CACHE["snap"], LIVE_CACHE.get("error")
        if snap is None:
            return self._json(502, {"error": "live prices failed: %s" % err})
        out = dict(snap, market_open=freshness.market_open(), error=err)
        return self._json(200, out)

    def do_HEAD(self):
        self._headers(405, "text/plain", 0)
        self.end_headers()

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/refresh" or not self.allow_refresh:
            return self.do_HEAD()
        if not self._authorized():
            return self._deny_auth()
        if self.headers.get("X-PKM-Refresh") != "1" or not self._host_ok():
            return self._json(403, {"error": "refused: needs the dashboard's own page on an allowed host"})
        if int(self.headers.get("Content-Length") or 0) > 1024:
            return self._json(413, {"error": "too large"})
        with REFRESH_LOCK:
            if REFRESH["running"]:
                return self._json(409, {"error": "a refresh is already running"})
            wait = COOLDOWN - (time.time() - REFRESH["last_start"])
            if REFRESH["last_start"] and wait > 0:
                return self._json(429, {"error": "just refreshed; try again in %d s" % wait})
            REFRESH.update(running=True, started=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), finished=None,
                           ok=None, tail=[], last_start=time.time())
        threading.Thread(target=run_refresh, args=(self.home, self.scope), daemon=True).start()
        return self._json(202, self._status())

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


def cmd_serve(a, h, cfg):
    root = os.path.join(h, "dashboard")
    if not os.path.exists(os.path.join(root, "data.json")):
        print("no dashboard yet: building it first")
        cmd_build(argparse.Namespace(all=False, days=500, standalone=None), h, cfg)
    loopback = ipaddress.ip_address(a.host).is_loopback if a.host not in ("localhost",) else True
    pw = os.environ.get("PKM_DASHBOARD_PASSWORD")
    if not loopback and not pw:
        sys.exit("refusing to listen on %s without a password: set PKM_DASHBOARD_PASSWORD "
                 "(and prefer a private network such as Tailscale; this server speaks plain HTTP)" % a.host)
    Handler.root, Handler.password, Handler.home = root, pw, h
    Handler.allow_refresh = bool(a.allow_refresh or os.environ.get("PKM_DASH_REFRESH") == "1")
    Handler.allow_live = bool(a.allow_live or os.environ.get("PKM_DASH_LIVE") == "1")
    Handler.scope = "all" if os.environ.get("PKM_SCOPE") == "all" else "watchlist"
    Handler.hostnames = tuple(n.strip().lower() for n in (os.environ.get("PKM_DASH_HOSTNAMES") or "").split(",") if n.strip())
    srv = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    print("dashboard on http://%s:%d/ (Ctrl+C to stop)%s%s%s" % (
        a.host, a.port, "" if loopback else ", user pkm",
        "; the page may fetch fresh data (--allow-refresh)" if Handler.allow_refresh else "",
        "; live prices on (--allow-live)" if Handler.allow_live else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--all", action="store_true", help="every liquid share (default: all if universe.json exists)")
    p.add_argument("--days", type=int, default=500, help="days of price history to include")
    p.add_argument("--standalone", help="write one self-contained HTML file here instead")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--allow-refresh", action="store_true",
                   help="let the page start a data fetch + rebuild (also: PKM_DASH_REFRESH=1)")
    p.add_argument("--allow-live", action="store_true",
                   help="let the page show live PSX prices (also: PKM_DASH_LIVE=1)")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"build": cmd_build, "serve": cmd_serve}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
