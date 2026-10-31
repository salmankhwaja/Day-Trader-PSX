#!/usr/bin/env python3
"""The website's price feed: fetch PSX and MUFAP, keep a year of history, publish it encrypted.

Runs on GitHub Actions (.github/workflows/feed.yml, or ci/feed.yml until you enable it), or by
hand. Writes the feed/ folder that the dashboard on GitHub Pages reads:

  feed/status.json            in the clear: when it last ran, what it has, errors. No prices.
  feed/key.json               salt + iterations for the passphrase, and a check value
  feed/psx/YYYY-MM.enc.json   one file per month: every share's close and volume, each session
  feed/meta.enc.json          names, sectors, Shariah flags, P/E, 52-week range, dividends
  feed/summary.enc.json       the market, ranked by the same Python code as the CLI: shares,
                              sectors, dividend calendar, MUFAP funds, buy ideas (backtested)
  feed/latest.enc.json        today's prices in PK Wealth's format, so PK Wealth reads the same feed

PSX restricts redistribution of its market data, so PSX numbers are written ONLY encrypted:
AES-256-GCM with a key from PBKDF2-SHA256 of the passphrase in the PSX_DATA_KEY secret. The
browser asks for the same passphrase and decrypts on the device. Without the secret, nothing
from PSX is fetched or written.

Requests per normal run: market watch (every share, one request), the KSE-100 history, the
payouts page, the MUFAP table, and a fifth of the company pages (each share's page is refreshed
once a week). A one-time --backfill downloads a year of history for every share (~10 minutes).

  PSX_DATA_KEY=... python3 tools/web_feed.py               # normal run
  PSX_DATA_KEY=... python3 tools/web_feed.py --backfill    # first run: a year of history
  PSX_DATA_KEY=... python3 tools/web_feed.py --mufap-only  # evening run: fund NAVs only
"""
import argparse
import base64
import datetime as dt
import gzip
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "psx-mufap", "scripts"))

import common as C  # noqa: E402
import freshness as FR  # noqa: E402
import pkdata  # noqa: E402
import psxinfo as P  # noqa: E402

FEED = os.path.join(ROOT, "feed")
ITER = 310000                 # PBKDF2 iterations (same as PK Wealth)
KEEP_MONTHS = 13              # history kept: a year and a month
COMPANY_SHARE = 5             # refresh 1/5 of the company pages per run: each share weekly
CHECK_TEXT = b"psx-feed-ok"
INDEX = "KSE100"
MIN_FUNDS = 20               # same for the MUFAP table
MIN_QUOTES = 20              # fewer shares than this on the market watch means the page changed


# ---------------------------------------------------------------- encryption

def b64(x):
    return base64.b64encode(x).decode()


def unb64(s):
    return base64.b64decode(s)


def derive(passphrase, salt, iterations=ITER):
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, iterations, 32)


def seal(obj, key, zipped=True):
    """{iv, data}: AES-256-GCM over the JSON (gzipped first, so the browser gunzips after decrypting)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    if zipped:
        raw = gzip.compress(raw, mtime=0)
    iv = os.urandom(12)
    return {"v": 1, "enc": "AES-256-GCM" + ("+gzip" if zipped else ""), "iv": b64(iv), "data": b64(AESGCM(key).encrypt(iv, raw, None))}


def unseal(doc, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = AESGCM(key).decrypt(unb64(doc["iv"]), unb64(doc["data"]), None)
    return json.loads(gzip.decompress(raw) if doc.get("enc", "").endswith("+gzip") else raw)


def pk_wealth_doc(obj, passphrase):
    """PK Wealth's own format (data/psx.enc.json): its own salt, not gzipped. Feed.decryptDoc reads it."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(derive(passphrase, salt)).encrypt(iv, json.dumps(obj, separators=(",", ":")).encode(), None)
    return {"format": "pk-wealth-psx", "v": 1, "enc": "AES-256-GCM/PBKDF2-SHA256", "iterations": ITER,
            "salt": b64(salt), "iv": b64(iv), "data": b64(ct), "updated": now_iso()}


def fingerprint(obj, key):
    """HMAC of the plaintext: tells whether a file really changed (encryption differs every time)
    without publishing anything a reader could check prices against."""
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()[:32]


# ---------------------------------------------------------------- files

def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def path(*p):
    return os.path.join(FEED, *p)


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, p)


class Store:
    """The encrypted feed on disk. Writes a file only when its content changed."""

    def __init__(self, passphrase):
        self.passphrase = passphrase
        kd = read_json(path("key.json"))
        if kd:
            key = derive(passphrase, unb64(kd["salt"]), kd["iterations"])
            try:
                ok = unseal(kd["check"], key) == CHECK_TEXT.decode()
            except Exception:  # noqa: BLE001  (a new passphrase: start the feed again)
                ok = False
            if not ok:
                print("PSX_DATA_KEY changed: the feed is re-encrypted from scratch", file=sys.stderr)
                shutil.rmtree(FEED, ignore_errors=True)
                kd = None
        if not kd:
            salt = os.urandom(16)
            key = derive(passphrase, salt)
            kd = {"v": 1, "kdf": "PBKDF2-SHA256", "iterations": ITER, "salt": b64(salt), "check": seal(CHECK_TEXT.decode(), key)}
            write_json(path("key.json"), kd)
        self.key = key
        self.prints = read_json(path("prints.json"), {})   # file -> HMAC of its plaintext
        self.changed = []

    def load(self, rel):
        doc = read_json(path(rel))
        return unseal(doc, self.key) if doc else None

    def save(self, rel, obj, ignore=()):
        """`ignore`: keys left out of the change check (timestamps), so a run with no new prices commits nothing."""
        fp = fingerprint({k: v for k, v in obj.items() if k not in ignore} if isinstance(obj, dict) else obj, self.key)
        if self.prints.get(rel) == fp and os.path.exists(path(rel)):
            return False
        write_json(path(rel), seal(obj, self.key))
        self.prints[rel] = fp
        self.changed.append(rel)
        return True

    def save_pk_wealth(self, rel, obj):
        fp = fingerprint({k: v for k, v in obj.items() if k != "fetched"}, self.key)
        if self.prints.get(rel) == fp and os.path.exists(path(rel)):
            return False
        write_json(path(rel), pk_wealth_doc(obj, self.passphrase))
        self.prints[rel] = fp
        self.changed.append(rel)
        return True

    def close(self):
        write_json(path("prints.json"), self.prints)


# ---------------------------------------------------------------- monthly price files
# {"month": "2026-10", "syms": [...], "days": {"2026-10-30": {"c": [...], "v": [...]}}}
# c and v line up with syms; null where a share didn't trade (or wasn't listed yet).

def month_of(day):
    return day[:7]


def put_rows(months, sym, rows):
    """Merge {date, close, volume} rows for one symbol into the month tables."""
    for r in rows:
        m = months.setdefault(month_of(r["date"]), {"month": month_of(r["date"]), "syms": [], "days": {}})
        if sym not in m["syms"]:
            m["syms"].append(sym)
            for d in m["days"].values():
                d["c"].append(None)
                d["v"].append(None)
        i = m["syms"].index(sym)
        d = m["days"].setdefault(r["date"], {"c": [None] * len(m["syms"]), "v": [None] * len(m["syms"])})
        d["c"][i] = round(float(r["close"]), 4)
        d["v"][i] = int(r.get("volume") or 0)


def rows_by_symbol(months):
    out = {}
    for m in sorted(months.values(), key=lambda m: m["month"]):
        for day in sorted(m["days"]):
            d = m["days"][day]
            for i, s in enumerate(m["syms"]):
                if i < len(d["c"]) and d["c"][i] is not None:
                    out.setdefault(s, []).append({"date": day, "open": d["c"][i], "close": d["c"][i],
                                                  "volume": d["v"][i] or 0})
    return out


def wanted_months(today):
    y, m = today.year, today.month
    out = []
    for _ in range(KEEP_MONTHS):
        out.append("%04d-%02d" % (y, m))
        m -= 1
        if not m:
            y, m = y - 1, 12
    return set(out)


# ---------------------------------------------------------------- the run

def fetch_market(store, months, meta, errors, backfill=False):
    """Market watch (one request) for today's prices; the KSE-100 history; optionally a year of
    every share's history."""
    try:
        quotes = FR.parse_market_watch(C.http_get(FR.MARKET_WATCH))
        if len(quotes) < MIN_QUOTES:
            raise ValueError("only %d quotes parsed" % len(quotes))
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "psx market watch", "error": repr(e)[:300]})
        return None
    day = FR.last_session()
    shares = meta.setdefault("shares", {})
    for s, q in quotes.items():
        info = shares.setdefault(s, {})
        if q.get("sector"):
            info["sector"] = q["sector"]
        idx = [x.strip().upper() for x in (q.get("listed_in") or "").split(",") if x.strip()]
        if idx:
            info["indices"] = idx
            info["shariah"] = any(x.startswith("KMI") for x in idx)
    # Don't record a holiday as a session: if every price and volume equals the last session's, skip.
    prev = rows_by_symbol({k: v for k, v in months.items()})
    same = sum(1 for s, q in quotes.items() if prev.get(s) and prev[s][-1]["close"] == q["current"]
               and prev[s][-1]["volume"] == (q.get("volume") or 0) and prev[s][-1]["date"] != day)
    if same > 0.9 * len(quotes):
        errors.append({"source": "psx market watch", "error": "prices unchanged since the last session (a holiday?): not recorded as %s" % day})
    else:
        for s, q in quotes.items():
            put_rows(months, s, [{"date": day, "close": q["current"], "volume": q.get("volume") or 0}])
    targets = [INDEX] + (sorted(quotes) if backfill else [])
    since = (dt.date.today() - dt.timedelta(days=31 * KEEP_MONTHS)).isoformat()
    prog = C.Progress("history", len(targets))
    for s in targets:
        try:
            rows = [r for r in pkdata.parse_psx(C.http_get(pkdata.PSX_EOD % s)) if r["date"] >= since]
            put_rows(months, s, rows)
            prog.step(s)
        except Exception as e:  # noqa: BLE001
            prog.step(s, ok=False)
            errors.append({"source": "psx history %s" % s, "error": repr(e)[:160]})
    return {"date": day, "quotes": quotes}


def fetch_names(meta, errors):
    try:
        for x in json.loads(C.http_get(C.PSX_HOST + "/symbols")):
            if isinstance(x, dict) and x.get("symbol"):
                meta.setdefault("shares", {}).setdefault(str(x["symbol"]).upper(), {})["name"] = x.get("name") or ""
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "psx symbols (names)", "error": repr(e)[:160]})


def fetch_companies(meta, errors, everything=False):
    """A fifth of the company pages each run (all with --backfill): P/E, 52-week range, dividends."""
    shares = sorted(meta.get("shares", {}))
    if not shares:
        return
    if everything:
        todo = shares
    else:
        part = dt.date.today().toordinal() % COMPANY_SHARE
        todo = [s for i, s in enumerate(shares) if i % COMPANY_SHARE == part]
    comps = meta.setdefault("companies", {})
    prog = C.Progress("company pages", len(todo))
    for s in todo:
        try:
            c = P.parse_company(C.http_get(C.PSX_HOST + "/company/" + s), s)
            comps[s] = {k: c.get(k) for k in ("name", "sector", "tags", "pe", "low_52w", "high_52w", "payouts", "fetched")}
            prog.step(s)
        except Exception as e:  # noqa: BLE001
            prog.step(s, ok=False)
            errors.append({"source": "psx company %s" % s, "error": repr(e)[:120]})


def fetch_payouts(meta, errors):
    try:
        rows = P.parse_payouts_page(C.http_get(P.PAYOUTS_URL))
        keep = {(r["symbol"], r.get("announced"), r["details"]): r for r in (meta.get("payouts") or []) + rows}
        meta["payouts"] = sorted(keep.values(), key=lambda r: r.get("announced") or "", reverse=True)[:1500]
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "psx payouts", "error": repr(e)[:160]})


def fetch_mufap(meta, errors):
    for url in (pkdata.MUFAP_URL,):
        try:
            date, funds = pkdata.parse_mufap(C.http_get(url, timeout=getattr(pkdata, "MUFAP_TIMEOUT", 60)))
            if len(funds) < MIN_FUNDS:
                raise ValueError("only %d funds parsed" % len(funds))
            meta["mufap"] = {"date": date, "funds": funds}
            hist = meta.setdefault("navs", {})
            for f in funds:   # NAV history for fund backtests and charts, last 260 reports
                hist.setdefault(f["fund"], {})[f.get("validity_date") or date] = f["nav"]
            for name, h in hist.items():
                if len(h) > 260:
                    hist[name] = dict(sorted(h.items())[-260:])
            return
        except Exception as e:  # noqa: BLE001
            errors.append({"source": "mufap " + url, "error": repr(e)[:160]})


def build_summary(months, meta, errors):
    """Rebuild a pkmarket data folder from the feed and run the same code as the CLI over it."""
    import dashboard
    import advice as A
    import portfolio as PF
    h = tempfile.mkdtemp(prefix="pkm-feed-")
    try:
        cfg_user = {"watchlist": [], "benchmark": INDEX, "risk_profile": "moderate"}
        with open(os.path.join(h, "config.json"), "w") as f:
            json.dump(cfg_user, f)
        for s, rows in rows_by_symbol(months).items():
            C.write_prices(C.price_path(h, s), rows)
        shares, comps = meta.get("shares", {}), meta.get("companies", {})
        uni = {s: {"name": (comps.get(s) or {}).get("name") or v.get("name"), "price": None, "shares_m": None,
                   "mcap_m": None, "tags": (comps.get(s) or {}).get("tags") or [], "shariah": bool(v.get("shariah"))}
               for s, v in shares.items() if s != INDEX}
        with open(os.path.join(h, "universe.json"), "w") as f:
            json.dump(uni, f)
        for s, v in shares.items():
            c = dict(comps.get(s) or {})
            c.update(symbol=s, name=c.get("name") or v.get("name"), sector=c.get("sector") or v.get("sector"))
            c.setdefault("payouts", [])
            P.save_company(h, c)
        with open(os.path.join(h, "payouts.json"), "w") as f:
            json.dump(meta.get("payouts") or [], f)
        mf = meta.get("mufap")
        if mf:
            pkdata.save_mufap(h, mf["date"], mf["funds"])
            hist = os.path.join(h, "mufap", "nav_history.csv")   # the NAV history save_mufap keeps
            cat = {f["fund"]: f["category"] for f in mf["funds"]}
            rows = [(d, name, cat.get(name, ""), nav) for name, hh in meta.get("navs", {}).items() for d, nav in hh.items()]
            if rows:
                import csv
                with open(hist, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["date", "fund", "category", "nav"])
                    for r in sorted(rows):
                        w.writerow(r)
        cfg = C.load_config(h)
        data = dashboard.build_data(h, cfg, all_=True, days=1)
        for k in ("series", "calendar", "mine", "portfolio", "proposal"):
            data.pop(k, None)
        # Buy ideas for the whole market, independent of anyone's holdings: entry, stop, target and the
        # backtest that passed. The browser sizes them to your own capital and cash.
        try:
            lg = PF.load(h)
            ideas, info = A.buy_ideas(h, cfg, lg, PF.summary(h, lg), n=8, all_=True)
            data["ideas"] = ideas
            data["ideas_info"] = {k: info.get(k) for k in ("screened", "tested", "note")}
        except Exception as e:  # noqa: BLE001
            errors.append({"source": "buy ideas", "error": repr(e)[:200]})
            data["ideas"] = []
        data["settings"] = {k: A.setting(cfg, k) for k in list(A.SHOWN) + ["vol_window", "trend_fast", "trend_slow",
                                                                          "review_lag_pct", "stop_limit_gap"]}
        # Every fund's NAV and rank in its category (the funds table above keeps the top 15 only), so a
        # fund you hold always has a NAV and a HOLD / REVIEW in the browser.
        try:
            import rank
            fdate, frows = rank.fund_rows(h)
            idx = {}
            for cat, fs in rank.rank_funds(frows).items():
                scored = [f for f in fs if f.get("score") is not None]
                for f in fs:
                    pos = scored.index(f) if f in scored else None
                    idx[f["fund"]] = {"nav": f["nav"], "date": f.get("validity_date") or fdate, "category": cat,
                                      "rank": None if pos is None else pos + 1, "of": len(scored)}
            data["fund_index"] = idx
        except SystemExit:
            data["fund_index"] = {}
        data["generated"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).strftime("%Y-%m-%d %H:%M")
        return data
    finally:
        shutil.rmtree(h, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", action="store_true", help="also a year of history and every company page (~20 min)")
    ap.add_argument("--mufap-only", action="store_true", help="fund NAVs only (the evening run)")
    a = ap.parse_args(argv)
    status = read_json(path("status.json"), {}) or {}
    status.update({"format": "psx-desk-feed", "v": 1, "updated": now_iso(), "errors": []})
    passphrase = os.environ.get("PSX_DATA_KEY", "")
    if not passphrase:
        status["psx"] = {"available": False, "note": "Set the PSX_DATA_KEY repository secret to switch the feed on."}
        write_json(path("status.json"), status)
        print("PSX_DATA_KEY is not set: nothing fetched. The feed stays off.")
        return 0
    errors = status["errors"]
    store = Store(passphrase)
    meta = store.load("meta.enc.json") or {}
    months = {}
    keep = wanted_months(dt.date.today())
    for name in sorted(os.listdir(path("psx"))) if os.path.isdir(path("psx")) else []:
        m = name.replace(".enc.json", "")
        if m in keep:
            months[m] = store.load("psx/" + name)
        else:
            os.remove(path("psx", name))   # older than a year: dropped
            store.prints.pop("psx/" + name, None)
    snap = None
    if not a.mufap_only:
        snap = fetch_market(store, months, meta, errors, backfill=a.backfill or not months)
        if a.backfill or not meta.get("shares") or not any(v.get("name") for v in meta.get("shares", {}).values()):
            fetch_names(meta, errors)
        fetch_payouts(meta, errors)
        fetch_companies(meta, errors, everything=a.backfill)
    fetch_mufap(meta, errors)
    months = {m: v for m, v in months.items() if m in keep}   # history older than a year is dropped
    for m, obj in sorted(months.items()):
        store.save("psx/%s.enc.json" % m, obj)
    store.save("meta.enc.json", meta)
    if snap:   # today's prices in PK Wealth's format, for PK Wealth on the same site
        items = {}
        for s, q in snap["quotes"].items():
            items[s] = {k: q.get(k) for k in ("current", "ldcp", "change_pct", "volume", "sector") if q.get(k) is not None}
            nm = (meta.get("shares", {}).get(s) or {}).get("name")
            if nm:
                items[s]["name"] = nm
        store.save_pk_wealth("latest.enc.json", {"source": "PSX Data Portal market watch", "url": FR.MARKET_WATCH,
                                                 "fetched": now_iso(), "date": snap["date"], "count": len(items), "items": items})
    if months:
        try:
            store.save("summary.enc.json", build_summary(months, meta, errors), ignore=("generated", "freshness"))
        except Exception as e:  # noqa: BLE001
            errors.append({"source": "summary", "error": repr(e)[:300]})
            traceback.print_exc()
    store.close()
    days = sorted({d for m in months.values() for d in m["days"]})
    status["psx"] = {"available": bool(months), "months": sorted(m for m in months), "sessions": len(days),
                     "first": days[0] if days else None, "last": days[-1] if days else None,
                     "shares": len(meta.get("shares", {})), "companies": len(meta.get("companies", {}))}
    status["mufap"] = {"date": (meta.get("mufap") or {}).get("date"), "funds": len((meta.get("mufap") or {}).get("funds") or [])}
    status["changed"] = store.changed
    write_json(path("status.json"), status)
    print("feed: %d sessions (%s .. %s), %d shares, MUFAP %s; changed: %s; %d errors" % (
        len(days), status["psx"]["first"], status["psx"]["last"], status["psx"]["shares"], status["mufap"]["date"],
        ", ".join(store.changed) or "nothing", len(errors)))
    for e in errors[:15]:
        print("  error: %s: %s" % (e["source"], e["error"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
