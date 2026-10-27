#!/usr/bin/env python3
"""A second opinion: buy / sell signals published by PakistaniBulls, next to this tool's own advice.

  signals.py pakistanibulls --from-file page.html   import a signal list you saved from your browser
                                                    (works with the free list and the members' list)
  signals.py pakistanibulls --terms                 show their terms, and switch on direct download
                                                    (--accept-terms / --decline-terms without the question)
  signals.py pakistanibulls --fetch                 download their public PSX signal list (after --terms)
  signals.py show [SYMBOL ...]                      what's on file: your watchlist and holdings by default

PakistaniBulls (pakistanibulls.com, run by Americanbulls.com LLC) publishes candlestick-pattern
signals for PSX shares: BUY, SELL, STAY LONG, STAY IN CASH, SHORT, STAY SHORT, with the price the
signal fired at, a level that would flip it, and the pattern behind it.

Their terms allow one copy for your own personal use and nothing more, so:
  - nothing here republishes their data; it stays in your data folder (signals/), never the repo;
  - direct download is off until you read their terms and switch it on (--terms);
  - the full list is for members: sign in with your browser, save the page (Ctrl+S, "web page,
    complete" or "HTML only"), and import that file. This tool never asks for your password.

Once a signal list is on file, `portfolio.py advise` and `check`, and the dashboard, show their
signal beside each holding and buy idea, and whether it agrees with this tool's suggestion. A
second opinion is information, not a tie-breaker: the two use different methods (candlestick
patterns vs backtested trend rules and your risk style).
"""
import argparse
import datetime as dt
import html as htmllib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

PB_URL = "https://www.pakistanibulls.com/SignalList.aspx?lang=en&MarketSymbol=KSE"
PB_MEMBERS_URL = "https://www.pakistanibulls.com/members/SignalList.aspx?lang=en&MarketSymbol=KSE"
PB_TERMS_URL = "https://www.pakistanibulls.com/Tos.aspx?lang=en"
PB_TERMS = ("Their terms of service say the site's contents may not be reproduced, in whole or in part, "
            "in any form, and that you may not copy or use any part of it for any purpose other than to "
            "print one copy for your own personal use.")
SOURCE = "pakistanibulls"

LABELS = {"sold at": "signal_price", "bought at": "signal_price", "shorted at": "signal_price",
          "covered at": "signal_price", "signal price": "signal_price",
          "buy level": "level", "sell level": "level", "short level": "level", "cover level": "level",
          "stop level": "level", "prev.close": "prev_close", "prev. close": "prev_close",
          "last close": "last_close", "gain%": "change_pct", "loss%": "change_pct"}
SIGNALS = ["STAY IN CASH", "STAY LONG", "STAY SHORT", "BUY", "SELL", "SHORT", "COVER"]
STANCE = {"BUY": "long", "STAY LONG": "long", "SELL": "out", "STAY IN CASH": "out", "COVER": "out",
          "SHORT": "short", "STAY SHORT": "short"}


def _num(s):
    s = (s or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _tokens(chunk):
    """Visible text of one row, as a list of short pieces."""
    chunk = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"</(div|td|a|span|p)>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", " ", chunk)  # markdown image links
    chunk = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\n\1\n", chunk)          # markdown links -> their text
    out = []
    for piece in re.split(r"[\n|]", htmllib.unescape(chunk)):
        piece = " ".join(piece.split())
        if piece and piece not in (".", "NameHeader"):
            out.append(piece)
    return out


def parse_signal_list(text):
    """{SYMBOL: {name, signal, stance, pattern, signal_price, signal_price_label, level, level_label,
    prev_close, last_close, change_pct}} from a PakistaniBulls signal list page (HTML, or the Markdown
    a web tool makes of it)."""
    if "DXDataRow" in text:
        chunks = re.split(r'<tr[^>]+id="[^"]*DXDataRow\d+', text)[1:]
    else:
        chunks = [l for l in text.splitlines() if "SignalPage.aspx" in l and "Ticker=" in l]
    out = {}
    for ch in chunks:
        m = re.search(r"Ticker=(?:%20|\s|\+)*([A-Za-z0-9.&-]+)", ch)
        if not m:
            continue
        sym = m.group(1).upper()
        names = [htmllib.unescape(re.sub(r"<[^>]+>", "", t)).strip() for t in
                 re.findall(r"<a[^>]+SignalPage\.aspx[^>]*>(.*?)</a>", ch, re.S)] or \
            re.findall(r"\[([^\]]+)\]\([^)]*SignalPage\.aspx", ch)
        names = [n for n in names if n and n.upper() != sym]
        pat = re.search(r'title="([^"]+)"', ch) or re.search(r'\]\([^)]*Pattern=\d+ "([^"]+)"\)', ch)
        toks = _tokens(ch)
        row = {"name": names[0] if names else None, "pattern": pat.group(1).title() if pat else None}
        for i, t in enumerate(toks):
            low = t.lower()
            if low == "last signal" and i + 1 < len(toks):
                sig = toks[i + 1].upper()
                row["signal"] = next((s for s in SIGNALS if sig.startswith(s)), sig)
            elif low in LABELS and i + 1 < len(toks) and _num(toks[i + 1]) is not None:
                key = LABELS[low]
                row[key] = _num(toks[i + 1])
                if key in ("signal_price", "level"):
                    row[key + "_label"] = t
                if key == "change_pct":
                    row["change_label"] = t
        if row.get("signal"):
            row["stance"] = STANCE.get(row["signal"])
            out[sym] = row
    return out


# ---------------------------------------------------------------- storage

def path(h):
    return os.path.join(h, "signals", SOURCE + ".json")


def load(h):
    try:
        with open(path(h), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(h, rows, origin):
    """Merge newly read rows into what's on file (each symbol keeps the time it was read)."""
    now = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
    snap = load(h) or {"source": "PakistaniBulls", "signals": {}}
    for sym, r in rows.items():
        snap["signals"][sym] = dict(r, read_at=now, origin=origin)
    snap["updated"] = now
    os.makedirs(os.path.dirname(path(h)), exist_ok=True)
    with open(path(h), "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1)
    return snap


def enabled(cfg):
    return bool(cfg.get("pakistanibulls_terms_ok"))


def fetch(h, cfg):
    if not enabled(cfg):
        raise ValueError("direct download is off: read their terms first (signals.py pakistanibulls --terms)")
    rows = parse_signal_list(C.http_get(PB_URL))
    if not rows:
        raise ValueError("no signals found on the page (it may have changed)")
    return save(h, rows, "download")


def lookup(h, cfg, symbols):
    """{SYMBOL: signal row + age_days} for the symbols that have a reasonably fresh signal on file."""
    snap = load(h)
    if not snap:
        return {}, None
    max_age = float(cfg.get("external_signals_max_age_days", 3))
    today = dt.date.today()
    out = {}
    for s in symbols:
        r = (snap.get("signals") or {}).get(s.upper())
        if not r:
            continue
        age = (today - dt.date.fromisoformat(r["read_at"][:10])).days
        if age <= max_age:
            out[s.upper()] = dict(r, age_days=age)
    return out, snap


def agreement(ours, stance):
    """Does their stance agree with our suggestion? ours: BUY, SELL, TRIM, REVIEW, HOLD, NOT NOW."""
    if not stance:
        return None
    if ours in ("BUY", "HOLD"):
        return "agrees" if stance == "long" else "disagrees"
    if ours in ("SELL", "TRIM", "NOT NOW"):
        return "agrees" if stance in ("out", "short") else "disagrees"
    if ours == "REVIEW":
        return "agrees (both cautious)" if stance in ("out", "short") else "mixed"
    return None


def describe(r):
    bits = [r["signal"]]
    if r.get("signal_price") is not None:
        bits.append("%s %.2f" % ((r.get("signal_price_label") or "at").lower(), r["signal_price"]))
    if r.get("level") is not None:
        bits.append("%s %.2f" % ((r.get("level_label") or "level").lower(), r["level"]))
    if r.get("pattern"):
        bits.append(r["pattern"].lower())
    return ", ".join(bits)


def second_opinion_rows(h, cfg, items):
    """items: [(symbol, our_action)] -> table rows and a note, or ([], note)."""
    found, snap = lookup(h, cfg, [s for s, _ in items])
    if not snap:
        return [], None
    rows = []
    for sym, ours in items:
        r = found.get(sym)
        if r:
            rows.append([sym, ours, describe(r), agreement(ours, r.get("stance")) or "", r["read_at"]])
        else:
            rows.append([sym, ours, "no recent signal on file", "", ""])
    return rows, "PakistaniBulls signals, read %s (%s); older than %s days are left out." % (
        snap.get("updated"), "downloaded" if any(v.get("origin") == "download" for v in snap["signals"].values())
        else "from pages you saved", cfg.get("external_signals_max_age_days", 3))


# ---------------------------------------------------------------- commands

def cmd_pb(a, h, cfg):
    if a.accept_terms or a.decline_terms:
        print(PB_TERMS + "\nFull terms: " + PB_TERMS_URL)
        C.write_user_config(h, {"pakistanibulls_terms_ok": bool(a.accept_terms)})
        print("Direct download %s." % ("on, for your own personal use" if a.accept_terms else "off"))
        return 0
    if a.terms:
        print(PB_TERMS)
        print("Full terms: %s" % PB_TERMS_URL)
        print("\nThis tool only keeps a copy in your own data folder for your own use, and never publishes it.")
        try:
            ok = input("Switch on direct download of their public signal list? [y/N] ").strip().lower().startswith("y")
        except EOFError:
            ok = False
        C.write_user_config(h, {"pakistanibulls_terms_ok": bool(ok)})
        print("Direct download %s." % ("on" if ok else "stays off; importing a page you saved still works"))
        return 0
    try:
        if a.from_file:
            with open(a.from_file, encoding="utf-8", errors="replace") as f:
                rows = parse_signal_list(f.read())
            if not rows:
                sys.exit("no signals found in %s: save the signal list page itself (HTML), not a screenshot" % a.from_file)
            snap = save(h, rows, "saved page")
        elif a.fetch:
            snap = fetch(h, cfg)
            rows = {k: v for k, v in snap["signals"].items() if v.get("origin") == "download"}
        else:
            sys.exit("use --from-file PAGE.html (a page you saved), or --terms then --fetch")
    except (OSError, ValueError) as e:
        sys.exit("PakistaniBulls: %s" % e)
    print("Read %d signals (%d on file). %s" % (len(rows), len(snap["signals"]),
                                               "The free page lists only some shares; members' pages list more."
                                               if len(rows) < 50 else ""))
    return cmd_show(argparse.Namespace(symbols=[], all=False), h, cfg)


def cmd_show(a, h, cfg):
    snap = load(h)
    if not snap:
        print("No PakistaniBulls signals on file: signals.py pakistanibulls --from-file PAGE.html")
        return 0
    if a.symbols:
        syms = [s.upper() for s in a.symbols]
    elif a.all:
        syms = sorted(snap["signals"])
    else:
        import freshness as F
        syms = list(dict.fromkeys([s.upper() for s in cfg["watchlist"]] + F.held_symbols(h)))
    rows = []
    for s in syms:
        r = snap["signals"].get(s)
        chg = "" if not r or r.get("change_pct") is None else "%s %+.2f%%" % (r.get("change_label") or "", r["change_pct"])
        rows.append([s, describe(r) if r else "none on file", chg, (r or {}).get("last_close") or "", (r or {}).get("read_at", "")])
    print("PakistaniBulls signals (updated %s). Candlestick-pattern signals from a third party, "
          "for your own use only." % snap.get("updated"))
    print(C.md_table(["Symbol", "Their signal", "Since the signal", "Their last close", "Read"], rows))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pakistanibulls", help="import (or download) PakistaniBulls' PSX signal list")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--from-file", help="a signal list page you saved from your browser")
    g.add_argument("--fetch", action="store_true", help="download the public list (after --terms)")
    g.add_argument("--terms", action="store_true", help="read their terms; switch direct download on or off")
    g.add_argument("--accept-terms", action="store_true", help="the same without the question: switch it on")
    g.add_argument("--decline-terms", action="store_true", help="switch direct download off")
    p = sub.add_parser("show")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"pakistanibulls": cmd_pb, "show": cmd_show}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
