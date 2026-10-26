#!/usr/bin/env python3
"""Your watchlist: the shares you follow. Rankings, buy ideas, daily downloads and the dashboard
start from it (unless you ask for the whole market with --all).

  watchlist.py                              list it: name, sector, Shariah, last price, 1-month move
  watchlist.py add LUCK DGKC [--fetch]      add shares (checked against the listed shares)
  watchlist.py remove TRG                   take shares off
  watchlist.py set OGDC PPL MARI            replace the whole list
  watchlist.py add --top 5 --sector cement [--shariah]
                                            add the best-ranked shares of a sector (or the
                                            largest by market cap when prices aren't downloaded)
  watchlist.py add --holdings               add every share you hold
  watchlist.py reset                        back to the starter list
  watchlist.py export FILE / import FILE    one symbol per line (or comma-separated)

It lives in config.json under "watchlist"; editing that file by hand works too. Shares you hold
are always included in advice and live prices, watchlisted or not.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import psxinfo as P  # noqa: E402


def current(h):
    return [s.upper() for s in C.load_config(h)["watchlist"]]


def save(h, symbols):
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    C.write_user_config(h, {"watchlist": symbols})
    return symbols


def check_symbols(h, symbols, force=False):
    """Split into (known, unknown) using universe.json, when there is one."""
    uni = P.load_universe(h)
    syms = [s.strip().upper() for s in symbols if s.strip()]
    if not uni or force:
        return syms, []
    bench = C.load_config(h)["benchmark"].upper()
    return [s for s in syms if s in uni or s == bench], [s for s in syms if s not in uni and s != bench]


def top_of(h, cfg, n, sector=None, shariah=False):
    """The n best-ranked listed shares of a sector (by score), else the n largest by market cap."""
    import rank
    uni = P.load_universe(h)
    if not uni:
        raise ValueError("no universe.json yet: run `pkdata.py universe` first")
    try:
        ranked, _, _ = rank.rank_stocks(h, cfg, None, "score", True, sector, shariah)
    except SystemExit:
        ranked = []
    if ranked:
        return [m["symbol"] for m in ranked[:n]], "ranking score"
    pool = []
    for s, u in uni.items():
        sec = (P.load_company(h, s) or {}).get("sector") or u.get("sector") or ""
        if sector and sector.lower() not in sec.lower():
            continue
        if shariah and not u.get("shariah"):
            continue
        pool.append((u.get("mcap_m") or 0, s))
    pool.sort(reverse=True)
    return [s for _, s in pool[:n]], "market cap (download prices to rank by score)"


def cmd_list(a, h, cfg):
    import rank
    wl = current(h)
    if not wl:
        print("Your watchlist is empty: watchlist.py add OGDC PPL ...")
        return 0
    uni = P.load_universe(h)
    held = set()
    try:
        import portfolio as PF
        held = {p["symbol"] for p in PF.holdings(h, PF.load(h))}
    except Exception:  # noqa: BLE001 -- no ledger yet
        pass
    rows = []
    for s in wl:
        info = rank.stock_info(h, cfg, s, uni=uni)
        path = C.price_path(h, s)
        pr = C.read_prices(path) if os.path.exists(path) else []
        m1 = (pr[-1]["close"] / pr[-22]["close"] - 1) if len(pr) > 22 else None
        rows.append([s + (" ☪" if info.get("shariah") else ""), (info.get("name") or "")[:32], (info.get("sector") or "")[:26],
                     "%.2f" % pr[-1]["close"] if pr else "no prices", pr[-1]["date"] if pr else "", C.fmt_pct(m1),
                     "yes" if s in held else ""])
    print("Watchlist: %d shares (config.json in %s)" % (len(wl), h))
    print(C.md_table(["Symbol", "Name", "Sector", "Last", "As of", "1M", "You hold"], rows))
    missing = [r[0].split()[0] for r in rows if r[3] == "no prices"]
    if missing:
        print("No prices yet for %s: pkdata.py psx %s" % (", ".join(missing), " ".join(missing)))
    if not uni:
        print("Tip: `pkdata.py universe` lets the watchlist check symbols and show names and Shariah status.")
    return 0


def fetch_new(h, symbols):
    import pkdata
    if symbols:
        print("Fetching prices and company pages for %s..." % ", ".join(symbols))
        pkdata.main(["--home", h, "psx"] + symbols)
        pkdata.main(["--home", h, "company"] + symbols)


def cmd_add(a, h, cfg):
    wl = current(h)
    new = list(a.symbols)
    how = None
    if a.top:
        try:
            picks, how = top_of(h, cfg, a.top, a.sector, a.shariah)
        except ValueError as e:
            sys.exit(str(e))
        new += picks
    if a.holdings:
        import portfolio as PF
        new += [p["symbol"] for p in PF.holdings(h, PF.load(h))]
    if not new:
        sys.exit("name symbols to add, or use --top N [--sector ...] or --holdings")
    ok, unknown = check_symbols(h, new, a.force)
    if unknown:
        print("Not listed on PSX (per universe.json): %s. Check the spelling, or add --force." % ", ".join(unknown))
    added = [s for s in dict.fromkeys(ok) if s not in wl]
    save(h, wl + added)
    print("Added %s%s. Watchlist now has %d shares." % (", ".join(added) or "nothing new",
                                                         " (top by %s)" % how if how else "", len(wl) + len(added)))
    if a.fetch:
        fetch_new(h, added)
    elif added:
        print("Download their prices: pkdata.py psx %s  (or add --fetch next time)" % " ".join(added))
    return 0


def cmd_remove(a, h, cfg):
    wl = current(h)
    gone = {s.upper() for s in a.symbols}
    missing = sorted(gone - set(wl))
    left = save(h, [s for s in wl if s not in gone])
    print("Removed %s. Watchlist now has %d shares.%s" % (
        ", ".join(sorted(gone & set(wl))) or "nothing", len(left),
        " (%s wasn't on it)" % ", ".join(missing) if missing else ""))
    print("Their price files stay in your data folder; holdings are always tracked anyway.")
    return 0


def cmd_set(a, h, cfg):
    ok, unknown = check_symbols(h, a.symbols, a.force)
    if unknown:
        sys.exit("Not listed on PSX (per universe.json): %s. Fix them, or add --force." % ", ".join(unknown))
    wl = save(h, ok)
    print("Watchlist set to %d shares: %s" % (len(wl), ", ".join(wl)))
    if a.fetch:
        fetch_new(h, wl)
    return 0


def cmd_reset(a, h, cfg):
    wl = save(h, C.DEFAULT_CONFIG["watchlist"])
    print("Watchlist back to the starter list (%d shares)." % len(wl))
    return 0


def cmd_export(a, h, cfg):
    with open(a.file, "w") as f:
        f.write("\n".join(current(h)) + "\n")
    print("wrote %s" % a.file)
    return 0


def cmd_import(a, h, cfg):
    with open(a.file) as f:
        syms = [s for line in f for s in line.replace(",", " ").split() if not s.startswith("#")]
    a.symbols = syms
    return cmd_set(a, h, cfg) if a.replace else cmd_add(argparse.Namespace(symbols=syms, top=None, holdings=False,
                                                                           force=a.force, fetch=a.fetch,
                                                                           sector=None, shariah=False), h, cfg)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    p = sub.add_parser("add")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--top", type=int, help="add the N best-ranked shares (with --sector / --shariah)")
    p.add_argument("--sector", help="part of a PSX sector name, e.g. cement")
    p.add_argument("--shariah", action="store_true")
    p.add_argument("--holdings", action="store_true", help="add every share you hold")
    p.add_argument("--force", action="store_true", help="skip the listed-share check")
    p.add_argument("--fetch", action="store_true", help="download prices and company pages for the new ones")
    p = sub.add_parser("remove")
    p.add_argument("symbols", nargs="+")
    p = sub.add_parser("set")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--force", action="store_true")
    p.add_argument("--fetch", action="store_true")
    sub.add_parser("reset")
    p = sub.add_parser("export")
    p.add_argument("file")
    p = sub.add_parser("import")
    p.add_argument("file")
    p.add_argument("--replace", action="store_true", help="replace the list instead of adding")
    p.add_argument("--force", action="store_true")
    p.add_argument("--fetch", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    if not os.path.exists(os.path.join(h, "config.json")):
        os.makedirs(h, exist_ok=True)
        C.write_user_config(h, {})
    cfg = C.load_config(h)
    return {None: cmd_list, "list": cmd_list, "add": cmd_add, "remove": cmd_remove, "set": cmd_set, "reset": cmd_reset,
            "export": cmd_export, "import": cmd_import}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
