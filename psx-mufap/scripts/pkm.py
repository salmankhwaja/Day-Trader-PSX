#!/usr/bin/env python3
"""One launcher for everything, made for phones (Pydroid 3, Termux) but fine anywhere.

  python3 pkm.py                     a numbered menu: pick a number, answer the prompts
  python3 pkm.py rank stocks --all   or pass any tool and its arguments straight through
                                     (tools: pkdata rank backtest propose paper portfolio funds
                                      advice dashboard daily risk sip watchlist signals)

Blank answers take the default shown in [brackets]. Nothing here places a real order.
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C  # noqa: E402

TOOLS = ["pkdata", "rank", "backtest", "propose", "paper", "portfolio", "funds", "dashboard", "daily", "risk", "sip",
         "watchlist", "signals"]


def call(tool, *args):
    """Run a tool's main() in this process, printing its output; never exits the menu."""
    print()
    try:
        mod = __import__(tool)
        mod.main(list(args))
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code)
    except KeyboardInterrupt:
        print("\n(stopped)")
    except Exception as e:  # a menu must survive a bad page or a typo
        print("error: %s: %s" % (type(e).__name__, e))


def ask(prompt, default=None, required=False):
    while True:
        tip = " [%s]" % default if default not in (None, "") else ""
        try:
            v = input("%s%s: " % (prompt, tip)).strip()
        except EOFError:
            v = ""
        if v:
            return v
        if default not in (None, "") or not required:
            return default
        print("  (needed)")


def yes(prompt, default=False):
    v = ask(prompt + " (y/n)", "y" if default else "n")
    return str(v).lower().startswith("y")


def fresh():
    """Every piece of advice asks first: the last fetch, a fresh fetch, or live prices?"""
    import freshness as F
    st = F.status(C.home(), C.load_config(C.home()), F.scope(C.home(), C.load_config(C.home())), funds=True)
    return {"stored": "--no-fetch", "fetch": "--fetch", "live": "--live"}[F.ask_mode(st, funds=True)]


def opt(flag, value):
    return [flag, str(value)] if value not in (None, "") else []


# ------------------------------------------------------------------ actions

def fetch_watchlist():
    call("pkdata", "psx", "--watchlist")
    call("pkdata", "company", "--watchlist")
    call("pkdata", "payouts")
    call("pkdata", "mufap")


def fetch_all():
    print("The whole market takes 15-20 minutes the first time (one polite request a second).")
    if yes("Go ahead", True):
        call("pkdata", "universe")
        call("pkdata", "company", "--all")
        call("pkdata", "psx", "--all")
        call("pkdata", "payouts")
        call("pkdata", "mufap")


def rank_stocks():
    scope = ask("Watchlist or all shares (w/a)", "w")
    args = ["stocks", "--top", ask("How many", "15")]
    if str(scope).lower().startswith("a"):
        args.append("--all")
        if yes("Shariah-compliant only"):
            args.append("--shariah")
        sector = ask("Sector contains (blank = all)", "")
        args += opt("--sector", sector)
    sort = ask("Sort by score / 1m / 3m / 1y / div_yield", "score")
    call("rank", *(args + ["--sort", sort, fresh()]))


def stock_advice():
    args = ["advise", "--buy", ask("How many buy ideas", "3")]
    if yes("Look for buys across all shares (needs the whole-market data)"):
        args.append("--all")
    if yes("Shariah-compliant buys only"):
        args.append("--shariah")
    call("portfolio", *(args + [fresh()]))


def check_share():
    sym = ask("Symbol (e.g. OGDC)", required=True).upper()
    args = ["check", sym]
    args += opt("--entry", ask("Price you'd pay (blank = last close)", ""))
    args += opt("--stop", ask("Your own stop (blank = computed)", ""))
    call("portfolio", *(args + [fresh()]))


def fund_advice():
    risk = ask("Risk: low / medium / high", "low")
    args = ["advise", "--risk", risk, "--top", ask("Funds per category", "3")]
    if yes("Shariah-compliant only"):
        args.append("--shariah")
    f = fresh()
    call("funds", *(args + [f]))
    if yes("Check the funds you hold too"):
        call("funds", "review", "--no-fetch")  # just fetched above, or chose not to


def record_trade(side):
    sym = ask("Symbol (e.g. OGDC)", required=True).upper()
    qty = ask("Quantity" + (" or 'all'" if side == "sell" else ""), required=True)
    price = ask("Price per share", required=True)
    args = [side, sym, qty, price]
    args += opt("--broker", ask("Broker (blank = default)", ""))
    args += opt("--date", ask("Date YYYY-MM-DD", dt.date.today().isoformat()))
    print("Charges from your contract note (blank = estimate from the broker's schedule):")
    args += opt("--commission", ask("  Commission", ""))
    args += opt("--taxes", ask("  Taxes (sales tax, CVT, CGT)", ""))
    args += opt("--other", ask("  Other (CDC, NCCPL, levies)", ""))
    if side == "buy":
        args += opt("--stop", ask("Your stop-loss price (blank = computed daily)", ""))
    print("\nAbout to record: %s %s %s @ %s %s" % (side.upper(), qty, sym, price, " ".join(args[4:])))
    if yes("Record it", True):
        call("portfolio", *args)


def record_fund():
    side = ask("Buy or sell a fund (b/s)", "b")
    fund = ask("Fund name, or a unique part of it", required=True)
    amount = ask("Amount in rupees" + (" or 'all'" if side.startswith("s") else ""), required=True)
    args = ["fund-buy" if side.lower().startswith("b") else "fund-sell", fund, amount]
    args += opt("--nav", ask("NAV you got (blank = latest MUFAP NAV)", ""))
    args += opt("--load-pct", ask("Load % (blank = 0)", ""))
    args += opt("--date", ask("Date YYYY-MM-DD", dt.date.today().isoformat()))
    if yes("Record it", True):
        call("portfolio", *args)


def my_portfolio():
    call("portfolio", "holdings")
    if yes("Show realised profit and loss"):
        call("portfolio", "pnl")
    if yes("Show costs by broker"):
        call("portfolio", "fees")


def brokers():
    call("portfolio", "broker", "presets")
    call("portfolio", "broker", "list")
    if yes("Add a broker"):
        name = ask("Your name for it (e.g. AKD)", required=True)
        preset = ask("Preset key from the table (blank = type your own rates)", "")
        args = ["broker", "add", name]
        if preset:
            args += ["--preset", preset]
        else:
            args += opt("--commission-pct", ask("Commission % of value", "0.15"))
            args += opt("--per-share", ask("Or rupees per share, whichever is higher", "0.03"))
            args += opt("--min-commission", ask("Minimum per trade", ""))
            args += opt("--sales-tax-pct", ask("Sales tax % on commission", "13"))
        if yes("Make it your default broker", True):
            args.append("--default")
        call("portfolio", *args)


def dashboard():
    h = C.home()
    out = os.path.join(h, "dashboard.html")
    call("dashboard", "build", "--standalone", out)
    print("\nOpen this file in your browser: %s" % out)
    if C.is_android():
        print("(Files app > Internal storage > pkmarket > dashboard.html > open with Chrome)")
    try:
        import webbrowser
        if yes("Try to open it now"):
            webbrowser.open("file://" + out)
    except Exception:
        pass


def settings():
    h = C.home()
    if not os.path.exists(os.path.join(h, "config.json")):
        call("pkdata", "init")
    print("\nData folder: %s" % h)
    call("watchlist", "list")
    print("\na) add shares   b) remove shares   c) replace the list   d) add the top N of a sector   e) add my holdings   f) leave it")
    c = (ask("Choose", "f") or "f").lower()
    if c == "a":
        call("watchlist", "add", *ask("Symbols to add (spaces or commas)", required=True).replace(",", " ").split())
    elif c == "b":
        call("watchlist", "remove", *ask("Symbols to remove", required=True).replace(",", " ").split())
    elif c == "c":
        call("watchlist", "set", *ask("The new list", required=True).replace(",", " ").split())
    elif c == "d":
        args = ["add", "--top", ask("How many", "5")] + opt("--sector", ask("Sector contains (blank = any)", ""))
        if yes("Shariah-compliant only"):
            args.append("--shariah")
        call("watchlist", *args)
    elif c == "e":
        call("watchlist", "add", "--holdings")
    if c in "abcde" and yes("Download prices for the new list now"):
        call("pkdata", "psx", "--watchlist")
    print("Other settings (costs, stops, tax) are in %s; edit it with any text editor." % os.path.join(h, "config.json"))


def second_opinion():
    print("PakistaniBulls publishes candlestick-pattern buy/sell signals. Their terms allow one copy for your own use.")
    print("a) import a signal list page I saved   b) download their public list   c) show what's on file")
    c = (ask("Choose", "c") or "c").lower()
    if c == "a":
        call("signals", "pakistanibulls", "--from-file", ask("Path of the saved page", required=True))
    elif c == "b":
        if not C.load_config(C.home()).get("pakistanibulls_terms_ok"):
            call("signals", "pakistanibulls", "--terms")
        call("signals", "pakistanibulls", "--fetch")
    else:
        call("signals", "show")


def risk_menu():
    print("a) take the risk quiz   b) compare the profiles   c) every setting   d) my portfolio's risk")
    print("e) size a position      f) change one setting")
    c = (ask("Choose", "d") or "d").lower()
    if c == "a":
        call("risk", "quiz")
    elif c == "b":
        call("risk", "profile")
        name = ask("Switch to (blank = keep)", "")
        if name:
            call("risk", "profile", name)
    elif c == "c":
        call("risk", "settings")
    elif c == "e":
        args = ["position", "--entry", ask("Entry price", required=True), "--stop", ask("Stop-loss price", required=True)]
        args += opt("--capital", ask("Capital (blank = your portfolio)", ""))
        args += opt("--risk-pct", ask("Risk % of capital (blank = your profile's)", ""))
        call("risk", *args)
    elif c == "f":
        call("risk", "set", ask("Setting name (see c)", required=True), ask("New value", required=True))
    else:
        call("risk", "portfolio", fresh())


def sip_menu():
    mode = (ask("Plan a monthly SIP, or find the SIP for a goal (p/g)", "p") or "p").lower()
    years = ask("Years", "10")
    if mode.startswith("g"):
        args = ["goal", "--target", ask("Target amount", required=True), "--years", years]
    else:
        args = ["plan", "--monthly", ask("Monthly amount", "25000"), "--years", years]
    src = (ask("Return from: profile mix / my rate / a fund / a share (p/r/f/s)", "p") or "p").lower()
    if src.startswith("r"):
        args += ["--rate", ask("Yearly return %", "14")]
    elif src.startswith("f"):
        args += ["--fund", ask("Fund name", required=True)]
    elif src.startswith("s"):
        args += ["--symbol", ask("Symbol", required=True)]
    args += opt("--step-up", ask("Raise it by % each year (blank = no)", ""))
    args += opt("--lump", ask("Starting amount (blank = none)", ""))
    args += opt("--inflation", ask("Inflation % to show today's rupees (blank = skip)", ""))
    call("sip", *args)


MENU = [
    ("Fetch data: my watchlist + funds", fetch_watchlist),
    ("Fetch data: the whole market (slow first time)", fetch_all),
    ("Rank stocks", rank_stocks),
    ("Stock advice: what to sell, hold, buy (with stop-losses)", stock_advice),
    ("Fund advice: which MUFAP funds", fund_advice),
    ("Record a BUY", lambda: record_trade("buy")),
    ("Record a SELL", lambda: record_trade("sell")),
    ("Record a mutual fund buy / sell", record_fund),
    ("My portfolio: holdings, profit and loss, fees", my_portfolio),
    ("Brokers: presets and charges", brokers),
    ("Run the whole daily update now", lambda: call("daily")),
    ("Dashboard: build the one-file version", dashboard),
    ("Watchlist and settings", settings),
    ("Risk: quiz, profiles, settings, my portfolio's risk", risk_menu),
    ("SIP calculator: plan or goal", sip_menu),
    ("Check one share: verdict + price calculator", check_share),
    ("Second opinion: PakistaniBulls buy/sell signals", second_opinion),
]


def menu():
    print("PSX & MUFAP  |  data folder: %s" % C.home())
    while True:
        print()
        for i, (label, _) in enumerate(MENU, 1):
            print("%2d. %s" % (i, label))
        print(" 0. Exit")
        choice = ask("Choose", "0")
        if choice in ("0", "q", "exit", None):
            return 0
        try:
            label, fn = MENU[int(choice) - 1]
        except (ValueError, IndexError):
            print("pick a number from the list")
            continue
        print("\n== %s" % label)
        fn()
        try:
            input("\n(Enter for the menu)")
        except EOFError:
            return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in TOOLS + ["advice"]:
        tool = "portfolio" if argv[0] == "advice" else argv[0]
        rest = ["advise"] + argv[1:] if argv[0] == "advice" else argv[1:]
        mod = __import__(tool)
        return mod.main(rest)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    return menu()


if __name__ == "__main__":
    sys.exit(main())
