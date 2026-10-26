#!/usr/bin/env python3
"""Build and serve the PSX / MUFAP dashboard.

  dashboard.py build [--all] [--days 500]          write <home>/dashboard/{index.html,app.js,data.json}
  dashboard.py build --standalone FILE.html        one self-contained file (open it anywhere)
  dashboard.py serve [--port 8787] [--host 127.0.0.1]

The dashboard has five views:
  Overview   KSE-100, sector league table, top-ranked shares, upcoming dividends
  Screener   every ranked share; filter by sector, Shariah, dividend yield, watchlist or holdings;
             tick shares to compare
  Compare    up to 6 shares: rebased price chart, returns, risk, valuation, dividends side by side
  Portfolio  the paper account: value vs KSE-100, allocation, holdings with review actions,
             dividends received, the latest proposal
  Funds      MUFAP rankings inside each category

`build` reads only local files written by the other tools. `serve` is a small read-only web
server for those three files: GET only, no directory listing, strict security headers. It binds
to 127.0.0.1 by default. To reach it from your phone, use a private network such as Tailscale and
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
import shutil
import statistics
import sys

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
                         "weight": r4(r.get("weight")), "trim_qty": r.get("trim_qty")})
        fees = PF.fee_table(lg)
        adv = None
        adir = os.path.join(h, "advice")
        if os.path.isdir(adir):
            files = sorted(f for f in os.listdir(adir) if f.endswith(".json"))
            if files:
                with open(os.path.join(adir, files[-1])) as f:
                    adv = json.load(f)
        mine = {"summary": {k: s[k] for k in ("value", "cost", "unrealised", "realised", "dividends", "fees", "cash")},
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
            with open(os.path.join(pdir, files[-1])) as f:
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

    return {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
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
    }


def cmd_build(a, h, cfg):
    data = build_data(h, cfg, True if a.all else None, a.days)
    blob = json.dumps(data, separators=(",", ":"), default=str)
    if a.standalone:
        with open(os.path.join(UI_DIR, "index.html")) as f:
            page = f.read()
        with open(os.path.join(UI_DIR, "app.js")) as f:
            js = f.read()
        inline = "<script>window.PKM_DATA=%s;</script>\n<script>%s</script>" % (
            blob.replace("</", "<\\/"), js)
        page = page.replace('<script src="app.js"></script>', inline)
        with open(a.standalone, "w") as f:
            f.write(page)
        print("standalone dashboard: %s (%.1f MB, %d shares)" % (a.standalone, len(page) / 1e6, len(data["stocks"])))
        return 0
    out = os.path.join(h, "dashboard")
    os.makedirs(out, exist_ok=True)
    for fn in ("index.html", "app.js"):
        shutil.copyfile(os.path.join(UI_DIR, fn), os.path.join(out, fn))
    with open(os.path.join(out, "data.json"), "w") as f:
        f.write(blob)
    print("dashboard built in %s: %d shares, %d dates, %.1f MB of data" % (
        out, len(data["stocks"]), len(data["calendar"]), len(blob) / 1e6))
    return 0


class Handler(http.server.BaseHTTPRequestHandler):
    root = None
    password = None
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

    def do_GET(self):
        if not self._authorized():
            self._headers(401, "text/plain", 0)
            self.send_header("WWW-Authenticate", 'Basic realm="pkm dashboard"')
            self.end_headers()
            return
        path = self.path.split("?", 1)[0].split("#", 1)[0]
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

    def do_HEAD(self):
        self._headers(405, "text/plain", 0)
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD

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
    Handler.root, Handler.password = root, pw
    srv = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    print("dashboard on http://%s:%d/ (Ctrl+C to stop)%s" % (a.host, a.port, "" if loopback else ", user pkm"))
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
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"build": cmd_build, "serve": cmd_serve}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
