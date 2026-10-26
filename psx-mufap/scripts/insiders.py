#!/usr/bin/env python3
"""psx-insiders: when directors, executives and sponsors buy or sell their own company's shares.

  insiders.py                         the last 30 days: your watchlist and holdings
  insiders.py --days 90 OGDC LUCK     any shares, any window
  insiders.py --all                   every listed share (one page each, one a second: about 10 minutes)
  insiders.py --new                   only what's appeared since the last run (for a daily schedule)
  insiders.py --cached                what's on file, no downloads

Pakistan's rules make insiders tell the market: directors, the CEO, executives and substantial
shareholders must report their dealings in the company's shares, and the company posts the notice
on PSX (titles like "Transaction in shares by Director", "Disclosure of interest", "Purchase of
shares by Sponsor"). This tool reads those notices from each company's PSX page (the
Announcements section) and lists them with their PDFs: the PDF says who, how many, at what price.

The PSX cousin of the US "Pelosi tracker": public filings, read as soon as they post. An insider
buying is one piece of information, not a signal by itself: they sell for school fees and buy to
show confidence. Read the notice.

Writes <home>/trader/insiders.json (and remembers what it has shown, for --new).
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402
import psxinfo as P  # noqa: E402


def find(h, symbols, days, today=None):
    today = today or C.pk_now().date()
    since = (today - dt.timedelta(days=days)).isoformat()
    out = []
    for s in symbols:
        for a in (P.load_company(h, s) or {}).get("announcements") or []:
            if a.get("tag") == "insider" and (a.get("date") or "") >= since:
                low = a["title"].lower()
                side = "buy" if any(w in low for w in ("purchase", "acqui", "buy")) else \
                    "sell" if any(w in low for w in ("sale", "sell", "dispos")) else "?"
                out.append(dict(a, symbol=s, side=side))
    out.sort(key=lambda x: (x.get("date") or "", x["symbol"]), reverse=True)
    return out


def main(argv=None):
    import freshness as F
    import news
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--new", action="store_true", help="only notices not shown before")
    ap.add_argument("--cached", action="store_true")
    ap.add_argument("--from-file", help="one company page you saved (with one symbol)")
    ap.add_argument("--now")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    syms = F.scope(h, cfg, a.symbols or None, a.all, held=not a.symbols)
    if a.from_file and len(syms) != 1:
        sys.exit("--from-file takes exactly one symbol")
    if a.all and not a.cached and not a.from_file:
        print("Reading %d company pages, one a second: about %d minutes." % (len(syms), len(syms) // 60 + 1))
    failed = [] if a.cached else news.refresh(h, syms, a.from_file)
    items = find(h, syms, a.days, desk.now(a.now).date())
    state = desk.read(h, "insiders.json", {}) or {}
    seen = set(state.get("seen", []))
    key = lambda x: "%s|%s|%s" % (x["symbol"], x.get("date"), x["title"])  # noqa: E731
    shown = [x for x in items if not (a.new and key(x) in seen)]
    desk.write(h, "insiders.json", {"made": desk.now(a.now).isoformat(timespec="minutes"), "days": a.days,
                                    "items": items, "seen": sorted(seen | {key(x) for x in items})})
    if a.json:
        print(json.dumps(shown, indent=1))
        return 0
    print("Insider dealings notices, last %d days, %d shares%s" % (a.days, len(syms), " (new only)" if a.new else ""))
    if shown:
        print(C.md_table(["Date", "Stock", "Buy/sell", "Notice", "PDF"],
                         [[x["date"], x["symbol"], x["side"], x["title"][:80], x.get("pdf") or ""] for x in shown]))
        print("The PDF names the person, the number of shares and the price.")
    else:
        print("None filed%s." % (" since the last run" if a.new else ""))
    if failed:
        print("Couldn't refresh: %s." % ", ".join(failed))
    print("Public disclosures, for information: not investment advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
