"""Before any advice: which prices? The last fetch, a fresh fetch, or live. Ask, then say.

Every advice command (portfolio.py advise / check, funds.py advise / review, propose.py,
rank.py stocks / funds, risk.py portfolio) takes one of:

  --no-fetch   last fetch: advise on the end-of-day data already on file
  --fetch      force fetch: download the end-of-day data for the shares (and funds) involved first
  --live       live: today's PSX prices (the portal's market watch, one request for every share),
               laid over the end-of-day history; shares whose history is behind are fetched first

With none, it asks when someone is at the keyboard; when run unattended (Claude, cron, the daily
update) it uses the last fetch and says so. After that one step every number is calculated on
the data in hand: fetching is the only step that touches the network. Live quotes are kept in
<home>/live.json and never written into the end-of-day price files.

The time of each fetch is kept in <home>/fetch_log.json, so the answer can say how fresh the
data is.
"""
import contextlib
import datetime as dt
import html as htmllib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

MARKET_WATCH = C.PSX_HOST + "/market-watch"
MODES = ("stored", "fetch", "live")


def add_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--fetch", action="store_true", help="force fetch: download end-of-day data first")
    g.add_argument("--no-fetch", action="store_true", help="last fetch: use the data already on file")
    g.add_argument("--live", action="store_true", help="live: today's PSX prices over the stored history")


# ---------------------------------------------------------------- live prices

def pk_now():
    """Pakistan time (UTC+5, no daylight saving)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=5)


def market_open(now=None):
    """Roughly whether PSX's regular session is on (Mon-Fri, 09:15-16:45 Pakistan time, which
    covers Friday's split session). Only used to label quotes and pace the dashboard."""
    now = now or pk_now()
    return now.weekday() < 5 and dt.time(9, 15) <= now.time() <= dt.time(16, 45)


def last_session(now=None):
    """The most recent weekday on or before today, as YYYY-MM-DD (PSX holidays aside)."""
    d = (now or pk_now()).date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def _num(v):
    v = (v or "").replace(",", "").replace("%", "").strip()
    neg = v.startswith("(") and v.endswith(")")
    v = v.strip("()")
    try:
        x = float(v)
    except ValueError:
        return None
    return -x if neg else x


CELL_RE = re.compile(r"<t([hd])([^>]*)>(.*?)</t[hd]>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
FIELDS = {"symbol": "symbol", "sector": "sector", "listed in": "listed_in", "ldcp": "ldcp", "open": "open",
          "high": "high", "low": "low", "current": "current", "change": "change", "change (%)": "change_pct",
          "volume": "volume"}
DEFAULT_ORDER = ["symbol", "sector", "listed_in", "ldcp", "open", "high", "low", "current", "change",
                 "change_pct", "volume"]


def parse_market_watch(text):
    """{SYMBOL: {ldcp, open, high, low, current, change, change_pct, volume, sector}} from the
    portal's market-watch table (HTML). Columns are matched by their headings when present."""
    order, quotes = None, {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = CELL_RE.findall(tr)
        if not cells:
            continue
        if all(k == "h" for k, _, _ in cells):
            names = [htmllib.unescape(TAG_RE.sub("", c)).strip().lower() for _, _, c in cells]
            order = [FIELDS.get(n, n) for n in names]
            continue
        cols = order or DEFAULT_ORDER
        row = {}
        for (kind, attrs, body), name in zip(cells, cols):
            m = re.search(r'data-search="([^"]+)"', attrs)
            txt = htmllib.unescape(TAG_RE.sub("", body)).strip()
            if name == "symbol":
                row["symbol"] = (m.group(1) if m else txt).split()[0].upper() if (m or txt) else None
            elif name in ("sector", "listed_in"):
                row[name] = txt
            else:
                o = re.search(r'data-order="([^"]+)"', attrs)
                row[name] = _num(o.group(1) if o else txt)
        if row.get("symbol") and row.get("current"):
            if row.get("change_pct") is None and row.get("ldcp"):
                row["change_pct"] = round(100 * (row["current"] / row["ldcp"] - 1), 2)
            quotes[row.pop("symbol")] = row
    return quotes


def live_path(h):
    return os.path.join(h, "live.json")


def fetch_live(h):
    """One request for every share's current price. Saves and returns the snapshot."""
    quotes = parse_market_watch(C.http_get(MARKET_WATCH))
    if len(quotes) < 5:
        raise ValueError("the market watch page had no prices (the portal may have changed)")
    now = pk_now()
    snap = {"fetched": now.strftime("%Y-%m-%d %H:%M:%S"), "date": last_session(now),
            "market_open": market_open(now), "quotes": quotes}
    with open(live_path(h), "w") as f:
        json.dump(snap, f)
    write_log(h, ["live"])
    return snap


def load_live(h):
    try:
        with open(live_path(h)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def use_live(snap):
    """Lay these quotes over every price read from now on (in this process)."""
    C.LIVE["date"] = snap["date"] if snap else None
    C.LIVE["fetched"] = snap.get("fetched") if snap else None
    C.LIVE["quotes"] = (snap or {}).get("quotes") or {}


def log_path(h):
    return os.path.join(h, "fetch_log.json")


def read_log(h):
    try:
        with open(log_path(h)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_log(h, what):
    log = read_log(h)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for w in what:
        log[w] = now
    with open(log_path(h), "w") as f:
        json.dump(log, f, indent=1)


def status(h, cfg, symbols=(), funds=False):
    """How fresh is the data these symbols (and funds) would be judged on?"""
    dates = {}
    for s in symbols:
        p = C.price_path(h, s)
        if os.path.exists(p):
            rows = C.read_prices(p)
            dates[s] = rows[-1]["date"] if rows else None
        else:
            dates[s] = None
    have = [d for d in dates.values() if d]
    out = {"symbols": dates, "missing": sorted(s for s, d in dates.items() if not d),
           "prices_newest": max(have) if have else None, "prices_oldest": min(have) if have else None,
           "last_fetch": read_log(h)}
    if funds:
        from pkdata import latest_mufap
        snap = latest_mufap(h)
        out["mufap_date"] = os.path.basename(snap)[:-4] if snap else None
    ref = out["prices_oldest"] or out.get("mufap_date")
    out["age_days"] = max(0, (dt.date.today() - dt.date.fromisoformat(ref)).days) if ref else None
    return out


def describe(st, funds=False):
    bits = []
    if st["prices_oldest"]:
        if st["prices_oldest"] == st["prices_newest"]:
            bits.append("prices as of %s" % st["prices_oldest"])
        else:
            bits.append("prices as of %s (oldest %s)" % (st["prices_newest"], st["prices_oldest"]))
    elif st["symbols"]:
        bits.append("no prices on file")
    if funds:
        bits.append("MUFAP as of %s" % (st.get("mufap_date") or "never"))
    if st["age_days"] is not None:
        bits.append("%d day%s old" % (st["age_days"], "" if st["age_days"] == 1 else "s"))
    last = st["last_fetch"].get("psx") or st["last_fetch"].get("mufap")
    if last:
        bits.append("last fetched %s" % last)
    if st.get("live"):
        lv = st["live"]
        bits.insert(0, "LIVE prices from PSX at %s (%s; %d of %d shares quoted)" % (
            lv["fetched"][11:16], "market open" if lv.get("market_open") else "market closed: last trades",
            lv["quoted"], lv["asked"]))
    return ", ".join(bits)


def fetch(h, cfg, symbols=(), funds=False, payouts=True, quiet=True):
    """Download prices for `symbols` (+ the benchmark), and optionally payouts and MUFAP."""
    import pkdata
    syms = list(dict.fromkeys([s.upper() for s in symbols] + [cfg["benchmark"].upper()]))
    jobs = []
    if syms:
        jobs.append(("psx", ["psx"] + syms))
    if payouts and symbols:
        jobs.append(("payouts", ["payouts"]))
    if funds:
        jobs.append(("mufap", ["mufap"]))
    done, failed = [], []
    for name, argv in jobs:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf if quiet else sys.stdout):
                rc = pkdata.main(["--home", h] + argv)
            (failed if rc else done).append(name)
        except SystemExit as e:
            failed.append(name)
            if not quiet:
                print(e.code)
        if quiet and name in failed:
            tail = [l for l in buf.getvalue().splitlines() if "FAILED" in l or "failed" in l][:5]
            for l in tail:
                print("  " + l.strip(), file=sys.stderr)
    return done, failed  # pkdata itself records each successful fetch in fetch_log.json


def held_symbols(h):
    """Shares in your real portfolio and the paper account."""
    out = []
    try:
        import portfolio as PF
        if os.path.exists(PF.lpath(h)):
            out += [p["symbol"] for p in PF.holdings(h, PF.load(h))]
    except Exception:  # a broken ledger shouldn't stop advice; portfolio.py reports it
        pass
    pp = os.path.join(h, "paper", "portfolio.json")
    if os.path.exists(pp):
        try:
            with open(pp) as fh:
                out += list(json.load(fh).get("positions") or {})
        except (OSError, ValueError):
            pass
    return out


def scope(h, cfg, symbols=None, all_=False, held=True):
    """The shares an advice command will look at: named ones, or watchlist / whole market, plus holdings."""
    import rank
    syms = rank.select_symbols(h, cfg, symbols, all_)
    if held:
        syms += held_symbols(h)
    return list(dict.fromkeys(s.upper() for s in syms))


def interactive():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def ask_mode(st, funds=False):
    try:
        ans = input("Data on file: %s.\nAdvise on [s] the last fetch, [f] a fresh fetch first, or [l] live prices? [s/f/l] "
                    % describe(st, funds)).strip().lower()
    except EOFError:
        ans = ""
    if ans.startswith(("f", "y")):
        return "fetch"
    if ans.startswith("l"):
        return "live"
    return "stored"


def decide(a, h, cfg, symbols=(), funds=False, payouts=True):
    """Apply --no-fetch / --fetch / --live (or ask), then print the data the advice is based on."""
    symbols = [s.upper() for s in symbols]
    out = sys.stderr if getattr(a, "json", False) else sys.stdout  # keep --json output clean
    st = status(h, cfg, symbols, funds)
    if getattr(a, "live", False):
        mode = "live"
    elif getattr(a, "fetch", False):
        mode = "fetch"
    elif getattr(a, "no_fetch", False):
        mode = "stored"
    elif interactive():
        mode = ask_mode(st, funds)
    else:
        mode = None  # unattended: the last fetch, and say so
    want = list(symbols)
    if mode == "live":  # only shares whose end-of-day history is behind need the slow download
        last = last_session()
        prev = (dt.date.fromisoformat(last) - dt.timedelta(days=1 if dt.date.fromisoformat(last).weekday() else 3)).isoformat()
        want = [s for s, d in st["symbols"].items() if not d or d < prev]
    if mode in ("fetch", "live") and (want or funds):
        if len(want) > 60:
            print("That's %d shares at about one a second: roughly %d minutes." % (len(want), len(want) // 60 + 1), file=out)
        print("Fetching %s%s..." % ("%d share price%s" % (len(want), "" if len(want) == 1 else "s") if want else "",
                                    (" and" if want else "") + " the MUFAP table" if funds else ""), file=out, flush=True)
        done, failed = fetch(h, cfg, want, funds, payouts and mode == "fetch")
        if failed:
            print("Some downloads failed (%s); using what's on file for those." % ", ".join(failed), file=out)
    live = None
    if mode == "live" and funds and not symbols:
        print("Funds have no live prices (NAVs are published once a day), so this is today's MUFAP table.", file=out)
    if mode == "live" and symbols:
        try:
            snap = fetch_live(h)
            use_live(snap)
            live = {"fetched": snap["fetched"], "market_open": snap["market_open"],
                    "quoted": sum(1 for s in symbols if s in snap["quotes"]), "asked": len(symbols)}
        except Exception as e:  # noqa: BLE001 -- fall back to the stored data, loudly
            print("Live prices failed (%s); using the last fetch instead." % e, file=out)
            mode = "stored"
    st = status(h, cfg, symbols, funds)
    st["live"] = live
    note = " (the last fetch; add --fetch for fresh end-of-day data or --live for live prices)" if mode is None else ""
    print("Based on %s%s.\n" % (describe(st, funds), note), file=out)
    st["mode"] = mode or "stored"
    st["fetched"] = mode == "fetch"
    return st
