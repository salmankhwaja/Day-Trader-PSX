"""Shared helpers for the PSX / MUFAP tools. Python 3.8+, standard library only.

Everything the tools write lives under one home folder:

    <home>/config.json          watchlist, costs, risk-free rate (optional)
    <home>/psx/<SYMBOL>.csv     daily prices: date,open,close,volume
    <home>/mufap/<date>.csv     one MUFAP performance snapshot per day
    <home>/mufap/nav_history.csv  date,fund,category,nav (grows a row per fund per run)
    <home>/paper/portfolio.json the paper-trading account

The home is ~/pkmarket (on Android: /storage/emulated/0/pkmarket when writable) unless
PKM_HOME or --home says otherwise. It is yours alone:
nothing in it belongs in the code repository.
"""
import csv
import json
import math
import os
import http.cookiejar
import re
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) pk-market-skill/1.0 (personal research)"
TRADING_DAYS = 245  # PSX trades Mon-Fri less public holidays; ~245 sessions a year

DEFAULT_CONFIG = {
    # Liquid KSE-100 names. Edit freely; any PSX symbol works.
    "watchlist": ["OGDC", "PPL", "MARI", "POL", "HUBC", "LUCK", "DGKC", "MLCF",
                  "MCB", "UBL", "HBL", "MEBL", "BAHL", "NBP", "ENGRO", "FFC",
                  "EFERT", "PSO", "SYS", "TRG"],
    "benchmark": "KSE100",
    # Round-trip cost model, in basis points per side (commission + taxes + slippage).
    # 20 bps a side is an assumption: set it to what your broker actually charges.
    "cost_bps_per_side": 20,
    "lot_size": 1,
    # Annual risk-free rate used in Sharpe ratios (e.g. a money-market yield).
    "risk_free_annual": 0.0,
    "paper_starting_cash": 1000000,
    # Withholding tax on cash dividends in the paper account. An assumption: check your rate.
    "dividend_tax": 0.15,
    # Face value per share is Rs 10 for most PSX shares; list exceptions, e.g. {"ABC": 5}.
    "face_values": {},
    # Your risk style. It sets every buy/sell/hold variable (stops, sizing, gates, ranking
    # weights...): see profiles.py, `risk.py settings`, and `risk.py quiz` to choose one.
    "risk_profile": "moderate",
}


ANDROID_SHARED = "/storage/emulated/0"


def is_android():
    return "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ


def default_home():
    """~/pkmarket, except on Android (Pydroid 3, Termux) where app home folders are hidden from
    file managers: there, use the phone's shared storage when it is writable, so the data, the
    ledger and the dashboard file can be opened, backed up and shared like any other file."""
    if is_android() and os.access(ANDROID_SHARED, os.W_OK):
        return os.path.join(ANDROID_SHARED, "pkmarket")
    return os.path.join("~", "pkmarket")


def home(arg=None):
    h = os.path.expanduser(arg or os.environ.get("PKM_HOME") or default_home())
    os.makedirs(h, exist_ok=True)
    return h


def read_user_config(h):
    p = os.path.join(h, "config.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def load_config(h, with_sources=False):
    """Defaults, then your risk profile's values, then your own settings (see profiles.py)."""
    import profiles
    cfg, src = profiles.resolve(read_user_config(h))
    return (cfg, src) if with_sources else cfg


def write_user_config(h, updates, remove=()):
    """Change keys in config.json, keeping everything else the user wrote."""
    raw = read_user_config(h)
    raw.update(updates)
    for k in remove:
        raw.pop(k, None)
    with open(os.path.join(h, "config.json"), "w") as f:
        json.dump(raw, f, indent=2)
    return raw


PSX_HOST = "https://dps.psx.com.pk"
# PSX's data portal now answers its data URLs (/timeseries/..., /indices/..., /payouts) only for
# requests that look like its own page's: a session cookie plus the per-session key every page
# carries as window.__ps = {"_k": "..."}, sent back as the X-Req-Id header (without them,
# /timeseries/eod/<SYMBOL> returns 404). We read the key from an ordinary page, once per run.
_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_JAR))
_PSX = {"key": None}
_KEY_RE = re.compile(r'window\.__ps\s*=\s*\{[^}]*?"_k"\s*:\s*"([^"]+)"')


def _fetch(url, timeout, data, headers):
    time.sleep(1.0)
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def psx_key(text=None, refresh=False):
    """The PSX portal's session key: taken from `text` if it's a portal page, else from its home page."""
    if text:
        m = _KEY_RE.search(text)
        if m:
            _PSX["key"] = m.group(1)
        return _PSX["key"]
    if _PSX["key"] and not refresh:
        return _PSX["key"]
    page = _fetch(PSX_HOST + "/", 30, None, {"Accept": "text/html"})
    m = _KEY_RE.search(page)
    if not m:  # the home page changed: any company page carries it too
        page = _fetch(PSX_HOST + "/company/OGDC", 30, None, {"Accept": "text/html"})
        m = _KEY_RE.search(page)
    _PSX["key"] = m.group(1) if m else None
    return _PSX["key"]


def http_get(url, timeout=30, data=None):
    """GET (or POST when data is given) with a polite user agent and a 1 request/second throttle.
    Requests to the PSX data portal carry its session cookie and key, like its own pages do."""
    if not url.startswith(PSX_HOST) or "/company/" in url:
        text = _fetch(url, timeout, data, None)
        if url.startswith(PSX_HOST):
            psx_key(text)
        return text
    for attempt in (0, 1):
        key = psx_key(refresh=attempt == 1)
        hdr = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, text/html, */*; q=0.01",
               "Referer": PSX_HOST + "/"}
        if key:
            hdr["X-Req-Id"] = key
        try:
            return _fetch(url, timeout, data, hdr)
        except urllib.error.HTTPError as e:
            if attempt == 1 or e.code not in (401, 403, 404, 419):
                raise


# ---------- price files ----------

def read_prices(path):
    """List of dicts {date, open, close, volume} sorted by date, from a CSV we wrote."""
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                close = float(row["close"])
            except (KeyError, ValueError):
                continue
            op = row.get("open")
            out.append({
                "date": row["date"],
                "open": float(op) if op not in (None, "") else close,
                "close": close,
                "volume": float(row.get("volume") or 0),
            })
    out.sort(key=lambda r: r["date"])
    return out


def write_prices(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = sorted({r["date"]: r for r in rows}.values(), key=lambda r: r["date"])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "close", "volume"])
        for r in rows:
            w.writerow([r["date"], r["open"], r["close"], int(r.get("volume") or 0)])
    return rows


def price_path(h, symbol):
    return os.path.join(h, "psx", symbol.upper() + ".csv")


def nav_series(h, fund):
    """Daily NAVs for one fund from nav_history.csv, as price rows (open = close = NAV)."""
    p = os.path.join(h, "mufap", "nav_history.csv")
    rows = {}
    if os.path.exists(p):
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                if r["fund"].lower() == fund.lower():
                    v = float(r["nav"])
                    rows[r["date"]] = {"date": r["date"], "open": v, "close": v, "volume": 0}
    return [rows[d] for d in sorted(rows)]


# ---------- statistics ----------

def pct(a, b):
    return (a / b - 1.0) if b else None


def daily_returns(closes):
    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]


def stdev(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def ann_vol(rets):
    s = stdev(rets)
    return s * math.sqrt(TRADING_DAYS) if s is not None else None


def max_drawdown(values):
    peak, mdd = None, 0.0
    for v in values:
        peak = v if peak is None or v > peak else peak
        if peak:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def sma(values, n, i):
    """Simple moving average of values[i-n+1 .. i]; None if not enough data."""
    if i + 1 < n:
        return None
    return sum(values[i - n + 1:i + 1]) / n


def rsi(values, n, i):
    if i < n:
        return None
    gains = losses = 0.0
    for k in range(i - n + 1, i + 1):
        d = values[k] - values[k - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def fmt_pct(x, digits=1):
    return "n/a" if x is None else ("%+.*f%%" % (digits, x * 100))


def fmt_pkr(x):
    return "n/a" if x is None else "PKR {:,.0f}".format(x)


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)
