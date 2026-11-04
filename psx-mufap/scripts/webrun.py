#!/usr/bin/env python3
"""The website's bridge to the command-line tools: every pkm.py menu item, run in the browser.

The website loads Python (Pyodide, Python compiled to WebAssembly) on first use, copies these scripts
into it and calls the functions below. Nothing leaves the device: the data folder lives in the
browser's memory, built from the prices the page has already decrypted, and the files the tools
write for you (config.json, your ledger, the paper account, proposals, desk plans and orders, alerts,
signals) are handed back to the page, which keeps them in this browser's storage.

  setup(home, months, meta, files)   build the data folder; restore your files
  run(tool, argv)                    run one tool's main(argv); returns {"out", "code"}
  user_files()                       {path: text} of every file that is yours (to keep)
  paper_data()                       the Paper tab's data (account, proposal) or None

Tools that need a live connection to PSX (live prices, intraday trades, fetching pages) can't reach
it from a browser and say so; everything else works on the feed's prices.
"""
import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Folders and files under the data folder that hold YOUR data (kept by the page); the rest is market
# data, rebuilt from the feed each visit.
USER_DIRS = ("portfolio", "paper", "proposals", "trader", "signals", "advice", "alerts")
USER_FILES = ("config.json",)
HOME = None


def setup(home, months, meta, files=None, config=None):
    """months/meta: JSON strings (or dicts) from the feed. files: {relative path: text} saved earlier."""
    global HOME
    import webhome
    os.environ["PKM_HOME"] = home
    os.environ.setdefault("PKM_VIEW", "table")
    HOME = home
    months = json.loads(months) if isinstance(months, str) else (months or {})
    meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
    files = json.loads(files) if isinstance(files, str) else (files or {})
    for rel, text in files.items():
        if ".." in rel.split("/"):
            continue
        p = os.path.join(home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    if config is not None and not os.path.exists(os.path.join(home, "config.json")):
        config = json.loads(config) if isinstance(config, str) else config
    else:
        config = None
    webhome.make_home(home, months, meta, config)
    return {"symbols": len(months and webhome.rows_by_symbol(months)), "home": home}


def run(tool, argv=()):
    """One tool's main(argv), its printed output captured. Never raises."""
    import importlib
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            mod = importlib.import_module(tool)
            r = mod.main([str(a) for a in argv])
            code = r if isinstance(r, int) else 0
        except SystemExit as e:
            if e.code not in (None, 0):
                code = e.code if isinstance(e.code, int) else 1
                if not isinstance(e.code, int):
                    print(e.code)
        except EOFError:
            code = 1
            print("(this step asks a question at the keyboard; use the form on the page instead)")
        except Exception as e:  # noqa: BLE001 - a page must survive a bad input
            code = 1
            msg = str(e)
            if isinstance(e, OSError) or "urlopen" in msg or "Protocol" in msg or "socket" in msg.lower():
                print("This needs a live connection to PSX or MUFAP, which a web page can't make (their sites "
                      "don't allow it). It works in the command-line tools; on the website, prices come from the feed.")
            else:
                print("error: %s: %s" % (type(e).__name__, e))
    return {"out": out.getvalue(), "code": code}


def user_files():
    """{relative path: text} of every file under the user folders, plus config.json."""
    out = {}
    for rel in USER_FILES:
        p = os.path.join(HOME, rel)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                out[rel] = f.read()
    for d in USER_DIRS:
        base = os.path.join(HOME, d)
        for root, _, names in os.walk(base):
            for n in names:
                p = os.path.join(root, n)
                try:
                    with open(p, encoding="utf-8") as f:
                        out[os.path.relpath(p, HOME).replace(os.sep, "/")] = f.read()
                except (UnicodeDecodeError, OSError):
                    pass
    return out


def paper_data():
    """{"portfolio": ..., "proposal": ...} as the dashboard's Paper tab shows them."""
    import common as C
    import dashboard
    import paper
    import rank
    h = HOME
    cfg = C.load_config(h)
    pf = paper.load(h) if os.path.exists(paper.ppath(h)) else None
    stocks = []
    if pf:
        held = [k for k, v in pf.get("positions", {}).items() if v.get("kind") == "stock"]
        try:
            ranked, _, _ = rank.rank_stocks(h, cfg, held or None, "score", False)
            stocks = [{"symbol": m["symbol"], "sector": m.get("sector"), "shariah": m.get("shariah")} for m in ranked]
        except SystemExit:
            stocks = []
    return json.dumps({"portfolio": dashboard.paper_section(h, cfg, pf, stocks),
                       "proposal": dashboard.latest_proposal(h)}, default=str)


def config():
    """config.json as the user wrote it (watchlist, risk profile, overrides), and the resolved settings."""
    import common as C
    raw = C.read_user_config(HOME)
    return json.dumps({"user": raw, "watchlist": C.load_config(HOME).get("watchlist", [])})
