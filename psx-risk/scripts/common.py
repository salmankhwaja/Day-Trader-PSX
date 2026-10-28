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
import datetime as dt
import json
import math
import os
import http.cookiejar
import gzip
import http.client
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

# Windows: output piped to a log or a scheduled task defaults to the old code page, which can't
# print the arrows and rupee tables; write UTF-8 there and never crash on a character.
if os.name == "nt":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

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
    # Second opinion (signals.py): third-party signals older than this many days are ignored.
    "external_signals_max_age_days": 3,
    # PakistaniBulls direct download: off until you read their terms (signals.py pakistanibulls --terms).
    "pakistanibulls_terms_ok": False,
    # How advise and holdings print: "cards" (short, one block per share, made for a phone
    # screen), "table" (wide Markdown tables) or "auto" (cards on Android, tables elsewhere).
    # The PKM_VIEW environment variable or a --view flag overrides it.
    "view": "auto",
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
        with open(p, encoding="utf-8") as f:
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
    with open(os.path.join(h, "config.json"), "w", encoding="utf-8") as f:
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
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with _OPENER.open(req, timeout=timeout) as r:
        body = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            body = gzip.decompress(body)  # MUFAP's page is ~1 MB of HTML, ~10x smaller compressed
        return body.decode("utf-8", "replace")


RETRY_WAITS = (3, 10)  # seconds before the second and third tries


def _transient(e):
    """A slow or briefly unavailable site: worth another try. A 404 or a bad certificate isn't."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in (429, 500, 502, 503, 504)
    if isinstance(e, urllib.error.URLError):
        return not isinstance(getattr(e, "reason", None), ssl.SSLError)
    return isinstance(e, (TimeoutError, ConnectionError, socket.timeout, http.client.IncompleteRead,
                          http.client.RemoteDisconnected))


def _fetch_retry(url, timeout, data, headers):
    for i, wait in enumerate(RETRY_WAITS + (None,)):
        try:
            return _fetch(url, timeout, data, headers)
        except Exception as e:  # noqa: BLE001
            if wait is None or not _transient(e):
                raise
            say("  %s: %s; trying again in %d s" % (url.split("/")[2], why(e), wait))
            time.sleep(wait)


def why(e):
    """A download error in words, with what to do for the common ones."""
    reason = getattr(e, "reason", None)
    if isinstance(reason, ssl.SSLError) or isinstance(e, ssl.SSLError):
        return ("the site's security certificate couldn't be checked (%s). On Windows or macOS, "
                "updating Python usually fixes this; on macOS run 'Install Certificates.command' in the "
                "Python folder" % (reason or e))
    if isinstance(e, urllib.error.HTTPError):
        return "the site answered %d %s" % (e.code, e.reason)
    if isinstance(e, (TimeoutError, socket.timeout)) or "timed out" in str(e):
        return "no answer in time (slow connection or a busy site)"
    if isinstance(e, urllib.error.URLError):
        return "couldn't reach the site (%s)" % reason
    return "%s: %s" % (type(e).__name__, e)


def say(text):
    """A progress note on stderr: it shows even when a tool's normal output is captured."""
    try:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _mins(sec):
    return "under a minute" if sec < 60 else "about %d min" % round(sec / 60.0)


class Progress:
    """Counts through a long download on one line: '[123/512] OGDC · 2 failed · about 6 min left'.
    Written to stderr, so it shows even when the tool's own output is captured (rank --fetch, the
    menu). In a terminal the line updates in place; in a log, a line every `every` items."""

    def __init__(self, label, total, every=50, stream=None):
        self.label, self.total, self.every = label, total, every
        self.s = stream or sys.stderr
        try:
            self.tty = self.s.isatty()
        except (AttributeError, ValueError):
            self.tty = False
        self.on = total > 1 and (self.tty or total > 20)
        self.n = self.bad = self.width = 0
        self.t0 = time.time()
        if self.on:
            self._line("%s: %d to fetch%s" % (label, total, ", %s at one a second" % _mins(total * 1.2)
                                               if total > 20 else ""), final=True)

    def _line(self, text, final=False):
        try:
            if self.tty:
                self.s.write("\r" + text + " " * max(0, self.width - len(text)) + ("\n" if final else ""))
                self.width = 0 if final else len(text)
            else:
                self.s.write(text + "\n")
            self.s.flush()
        except (OSError, ValueError):
            pass

    def clear(self):
        """Call before printing a normal line, so it doesn't land on top of the counter."""
        if self.on and self.tty and self.width:
            try:
                self.s.write("\r" + " " * self.width + "\r")
                self.s.flush()
            except (OSError, ValueError):
                pass
            self.width = 0

    def step(self, item, ok=True):
        self.n += 1
        self.bad += 0 if ok else 1
        if not self.on:
            return
        left = (time.time() - self.t0) / self.n * (self.total - self.n)
        text = "  [%d/%d] %-8s%s%s" % (self.n, self.total, item, " · %d failed" % self.bad if self.bad else "",
                                       " · %s left" % _mins(left) if self.n >= 3 and self.n < self.total else "")
        last = self.n == self.total
        if self.tty:
            self._line(text, final=last)
        elif self.n % self.every == 0 or last:
            self._line(text)


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
        text = _fetch_retry(url, timeout, data, None)
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
            return _fetch_retry(url, timeout, data, hdr)
        except urllib.error.HTTPError as e:
            if attempt == 1 or e.code not in (401, 403, 404, 419):
                raise


# ---------- the PSX clock (Pakistan time, UTC+5, no daylight saving) ----------
# Regular market, from PSX's trading-hours page: Monday-Thursday open 09:32-15:30 (pre-open 09:15);
# Friday two sessions, 09:17-12:00 and 14:32-16:30 (pre-opens 09:00 and 14:15). Holidays aside.
PSX_SESSIONS = {d: [("09:32", "15:30")] for d in range(4)}
PSX_SESSIONS[4] = [("09:17", "12:00"), ("14:32", "16:30")]
PSX_PRE_OPEN = {d: "09:15" for d in range(4)}
PSX_PRE_OPEN[4] = "09:00"
# Scrip-level price limits ("circuit breakers"): a share can't trade more than this far from the
# previous day's close in a day. Defaults: 10%, or Rs 1 when that is wider; set circuit_limit_pct /
# circuit_floor_rs in config.json if PSX changes them.
CIRCUIT_PCT, CIRCUIT_FLOOR = 10.0, 1.0


def pk_now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=5)


def _at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m))


def sessions(day):
    """[(open, close), ...] datetimes for a calendar day (empty at weekends)."""
    return [(_at(day, a), _at(day, b)) for a, b in PSX_SESSIONS.get(day.weekday(), [])]


def market_state(now=None):
    """'open', 'pre-open', 'break' (Friday lunch), 'closed' (before or after), or 'weekend'."""
    now = now or pk_now()
    ss = sessions(now.date())
    if not ss:
        return "weekend"
    for i, (a, b) in enumerate(ss):
        if a <= now < b:
            return "open"
        if i == 0 and _at(now.date(), PSX_PRE_OPEN[now.weekday()]) <= now < a:
            return "pre-open"
        if i > 0 and ss[i - 1][1] <= now < a:
            return "break"
    return "closed"


def close_time(day):
    """When the day's trading ends (the last session's close), or None at weekends."""
    ss = sessions(day)
    return ss[-1][1] if ss else None


def circuit_band(ldcp, cfg=None):
    """(lowest, highest) price a share may trade at today, from the last day's close."""
    pct = float((cfg or {}).get("circuit_limit_pct", CIRCUIT_PCT))
    floor = float((cfg or {}).get("circuit_floor_rs", CIRCUIT_FLOOR))
    w = max(ldcp * pct / 100.0, floor)
    return round(max(ldcp - w, 0.01), 2), round(ldcp + w, 2)


# ---------- price files ----------

# Live prices (freshness.py --live): today's PSX quotes laid over the end-of-day files while
# advice is calculated. Never written to the price files; the evening download replaces them.
LIVE = {"date": None, "fetched": None, "quotes": {}}
CLOSE_TIME = "15:30"  # PSX's regular close, Pakistan time: the time stamp of an end-of-day price


def read_prices(path, live=True):
    """List of dicts {date, open, close, volume} sorted by date, from a CSV we wrote.
    With live quotes loaded (and live=True), today's quote is the last row."""
    out = _read_csv_prices(path)
    if live and LIVE["quotes"] and os.path.basename(os.path.dirname(path)) == "psx":
        q = LIVE["quotes"].get(os.path.splitext(os.path.basename(path))[0].upper())
        if q and q.get("current"):
            row = {"date": LIVE["date"], "open": q.get("open") or q["current"], "close": q["current"],
                   "volume": float(q.get("volume") or 0), "live": True}
            if out and out[-1]["date"] == LIVE["date"]:
                out[-1] = row
            elif not out or out[-1]["date"] < LIVE["date"]:
                out.append(row)
    return out


def _read_csv_prices(path):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
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
    with open(path, "w", newline="", encoding="utf-8") as f:
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
        with open(p, newline="", encoding="utf-8") as f:
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


# ---------------------------------------------------------------- phone cards

VIEWS = ("auto", "cards", "table")
CARD_WIDTH = 34


def view_mode(cfg=None, arg=None):
    """'cards' or 'table': the --view flag, then PKM_VIEW, then config "view"; auto = cards on Android."""
    v = (arg or os.environ.get("PKM_VIEW") or (cfg or {}).get("view") or "auto").strip().lower()
    if v not in ("cards", "table"):
        v = "cards" if is_android() else "table"
    return v


def colour(text, code):
    """ANSI colour on a terminal (Termux included); plain text when piped or NO_COLOR is set."""
    import sys
    if code and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None:
        return "\033[1;%sm%s\033[0m" % (code, text)
    return text


def card_rule():
    return "\u2501" * CARD_WIDTH


def card_wrap(text, bullet="\u2022 "):
    """One bullet point, wrapped to the card width with a hanging indent."""
    import textwrap
    return textwrap.fill(text, CARD_WIDTH, initial_indent=bullet, subsequent_indent=" " * len(bullet),
                         break_on_hyphens=False)


def num(x, digits=2):
    return "n/a" if x is None else "{:,.{d}f}".format(x, d=digits)


def rs(x, sign=False):
    """Rupees, short: 'Rs 7,336' or with sign=True 'Rs +7,336' / 'Rs -7,336'."""
    if x is None:
        return "n/a"
    return ("Rs {:+,.0f}" if sign else "Rs {:,.0f}").format(x)


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)
