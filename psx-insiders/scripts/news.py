#!/usr/bin/env python3
"""psx-news: what each share you follow has announced to PSX, and what might move it.

  news.py                          the last 3 days: your watchlist and holdings
  news.py --days 14 OGDC MARI      any shares, any window
  news.py --setups                 the shares in today's scanner results
  news.py --cached                 what's on file, no downloads
  news.py OGDC --from-file page.html   a company page you saved

Source: each company's page on the PSX Data Portal (https://dps.psx.com.pk/company/<SYMBOL>), whose
Announcements section lists Financial Results, Board Meetings and Others, with the PDF of each
notice. One page per share, one a second. Every item is tagged:

  results    financial results, quarterly / half-yearly / annual reports
  payout     dividends, bonus and right shares, book closures
  board      board meetings and closed periods (results often follow)
  meeting    AGM / EOGM notices and resolutions
  insider    directors', executives' and sponsors' dealings in the shares (see psx-insiders)
  deal       acquisitions, mergers, tender offers, buy-backs, delisting
  material   material / price-sensitive information
  other      everything else (production updates, notices to shareholders...)

It also flags what matters for a short-term trade: a board meeting coming up (results can land
mid-trade), a book closure (the price drops by the dividend on the ex-date), and today's move if
live prices are on file (pkdata.py live, or --live).

Writes <home>/trader/news.json. Read the PDF before acting on anything: titles can mislead.
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

FLAG = {"results": "!", "payout": "$", "board": "!", "insider": "*", "deal": "!", "material": "!"}


def refresh(h, symbols, from_file=None):
    """Download each company page again (announcements change daily). Returns failures."""
    failed = []
    for s in symbols:
        try:
            if from_file:
                with open(from_file, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            else:
                text = C.http_get(P.COMPANY_URL % s)
            c = P.parse_company(text, s)
            if not c.get("name") and not c.get("announcements"):
                raise ValueError("no company data on the page")
            P.save_company(h, c)
        except Exception as e:  # noqa: BLE001
            failed.append("%s (%s)" % (s, str(e)[:60]))
    return failed


def gather(h, symbols, days, today=None):
    today = today or C.pk_now().date()
    since = (today - dt.timedelta(days=days)).isoformat()
    items, upcoming = [], []
    market = P.load_payouts(h)
    for s in symbols:
        c = P.load_company(h, s) or {}
        for a in c.get("announcements") or []:
            if (a.get("date") or "") >= since:
                items.append(dict(a, symbol=s))
        for pay in list(c.get("payouts") or []) + [m for m in market if m["symbol"] == s]:
            bc = pay.get("bc_from")
            if bc and today.isoformat() <= bc <= (today + dt.timedelta(days=14)).isoformat():
                upcoming.append({"symbol": s, "date": bc, "what": "book closure for %s: buy before the ex-date to get it; "
                                 "the price usually drops by about the dividend then" % pay.get("details")})
                break
        board = next((a for a in c.get("announcements") or [] if a.get("tag") == "board"
                      and (a.get("date") or "") >= (today - dt.timedelta(days=10)).isoformat()), None)
        if board:
            upcoming.append({"symbol": s, "date": board["date"], "what": "board meeting notice (%s): results or a payout "
                             "may be announced; a trade held over it carries that risk" % board["title"].lower()})
    items.sort(key=lambda x: (x.get("date") or "", x["symbol"]), reverse=True)
    return items, upcoming


def todays_moves(h, symbols):
    import freshness as F
    snap = F.load_live(h)
    if not snap or snap.get("date") != C.pk_now().date().isoformat():
        return {}, None
    return {s: snap["quotes"][s] for s in symbols if s in snap["quotes"]}, snap.get("fetched")


def main(argv=None):
    import freshness as F
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--setups", action="store_true", help="the shares in trader/setups.json")
    ap.add_argument("--cached", action="store_true", help="no downloads: what's on file")
    ap.add_argument("--from-file", help="one company page you saved (with one symbol)")
    ap.add_argument("--live", action="store_true", help="also fetch today's live prices (one request)")
    ap.add_argument("--now")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    if a.setups:
        syms = [x["symbol"] for x in (desk.read(h, "setups.json", {}) or {}).get("setups", [])]
    else:
        syms = F.scope(h, cfg, a.symbols or None, held=not a.symbols)
    syms = list(dict.fromkeys(s.upper() for s in syms))
    if a.from_file and len(syms) != 1:
        sys.exit("--from-file takes exactly one symbol")
    failed = [] if a.cached else refresh(h, syms, a.from_file)
    if a.live:
        try:
            F.fetch_live(h)
        except Exception as e:  # noqa: BLE001
            print("Live prices failed (%s)." % e)
    today = desk.now(a.now).date()
    items, upcoming = gather(h, syms, a.days, today)
    moves, at = todays_moves(h, syms)
    res = {"made": desk.now(a.now).isoformat(timespec="minutes"), "days": a.days, "symbols": syms, "items": items,
           "upcoming": upcoming, "moves": moves, "moves_at": at, "failed": failed}
    desk.write(h, "news.json", res)
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print("PSX announcements, last %d day%s, %d shares%s" % (a.days, "" if a.days == 1 else "s", len(syms),
                                                            " (from file, not refreshed)" if a.cached else ""))
    if items:
        print(C.md_table(["Date", "Stock", "Type", "Title", "PDF"],
                         [[x["date"], x["symbol"], FLAG.get(x["tag"], "") + x["tag"], x["title"][:90], x.get("pdf") or ""]
                          for x in items]))
    else:
        print("Nothing announced in that window.")
    if upcoming:
        print("\nCOMING UP")
        for u in upcoming:
            print("  %s %s: %s" % (u["date"], u["symbol"], u["what"]))
    if moves:
        print("\nTODAY (live at %s)" % at)
        print(C.md_table(["Stock", "Price", "Change", "Volume"],
                         [[s, "%.2f" % q["current"], "%+.2f%%" % (q.get("change_pct") or 0), "{:,.0f}".format(q.get("volume") or 0)]
                          for s, q in sorted(moves.items(), key=lambda kv: -abs(kv[1].get("change_pct") or 0))]))
    if failed:
        print("\nCouldn't refresh: %s (showing what's on file for those)." % ", ".join(failed))
    print("\nTitles are a summary: open the PDF before acting. " + desk.DISCLAIMER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
