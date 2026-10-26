"""Before any advice: fetch fresh data, or use what's on file? Ask, then say which was used.

Every advice command (portfolio.py advise / check, funds.py advise / review, propose.py,
rank.py stocks / funds, risk.py portfolio) takes:

  --fetch      download fresh data for the shares (and funds) involved, then advise
  --no-fetch   advise on the data already on file

With neither, it asks when someone is at the keyboard ("Prices are from 2026-10-24, 2 days old.
Fetch fresh data first? [y/N]"); when run unattended (by Claude, cron or the daily update) it
doesn't fetch, and states the data's date at the top of the output. Either way every number
after that point is calculated on the data on file at that moment: fetching is the only step
that touches the network.

The time of each fetch is kept in <home>/fetch_log.json, so the answer can say how fresh the
data is.
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def add_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--fetch", action="store_true", help="download fresh data first")
    g.add_argument("--no-fetch", action="store_true", help="use the data already on file")


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


def decide(a, h, cfg, symbols=(), funds=False, payouts=True):
    """Apply --fetch / --no-fetch / ask, then print the data date the advice is based on."""
    symbols = [s.upper() for s in symbols]
    out = sys.stderr if getattr(a, "json", False) else sys.stdout  # keep --json output clean
    st = status(h, cfg, symbols, funds)
    want = None
    if getattr(a, "fetch", False):
        want = True
    elif getattr(a, "no_fetch", False):
        want = False
    elif interactive():
        try:
            ans = input("Data on file: %s. Fetch fresh data first? [y/N] " % describe(st, funds)).strip().lower()
        except EOFError:
            ans = ""
        want = ans.startswith("y")
    if want and len(symbols) > 60:
        print("That's %d shares at about one a second: roughly %d minutes." % (len(symbols), len(symbols) // 60 + 1), file=out)
    if want:
        print("Fetching %s%s..." % ("%d share price%s" % (len(set(symbols)), "" if len(set(symbols)) == 1 else "s")
                                    if symbols else "", " and the MUFAP table" if funds else ""), file=out, flush=True)
        done, failed = fetch(h, cfg, symbols, funds, payouts)
        if failed:
            print("Some downloads failed (%s); using what's on file for those." % ", ".join(failed), file=out)
        st = status(h, cfg, symbols, funds)
    note = "" if want else ("" if getattr(a, "no_fetch", False) or want is False else
                            " (not refreshed: add --fetch to download first)")
    print("Based on %s%s.\n" % (describe(st, funds), note), file=out)
    st["fetched"] = bool(want)
    return st
