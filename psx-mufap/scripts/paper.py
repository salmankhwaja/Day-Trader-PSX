#!/usr/bin/env python3
"""Paper trading: a pretend PKR account for PSX stocks and MUFAP funds. No real orders, ever.

  paper.py init [--cash 1000000] [--force]       open (or reset) the account
  paper.py buy SYMBOL QTY [--price P]            buy shares at P, or at the latest close
  paper.py sell SYMBOL QTY|all [--price P]
  paper.py invest "FUND NAME" AMOUNT             buy fund units at the latest MUFAP NAV
  paper.py redeem "FUND NAME" AMOUNT|all
  paper.py status                                holdings, value, profit/loss, vs KSE100
  paper.py log [--last 20]                       trade history
  paper.py signals --strategy sma|breakout|rsi|momentum [--apply]
        turn a backtested strategy into orders for the watchlist. Without --apply it only
        PRINTS the orders; with --apply it books them in the paper account.

The account lives in <home>/paper/portfolio.json. It is just a file: keep a copy somewhere
safe (your GitHub repo works) and put it back in place next session to continue.

Fills use the latest close you have downloaded (or the --price you give), minus costs of
cost_bps_per_side from config.json. Funds are bought and redeemed at NAV with no load;
if your fund charges a front-end or back-end load, pass it as --fee-pct.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import backtest as B  # noqa: E402
from rank import fund_rows  # noqa: E402


def ppath(h):
    return os.path.join(h, "paper", "portfolio.json")


def load(h):
    p = ppath(h)
    if not os.path.exists(p):
        sys.exit("no paper account yet: run `paper.py init` (or put your saved portfolio.json at %s)" % p)
    with open(p) as f:
        return json.load(f)


def save(h, pf):
    p = ppath(h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(pf, f, indent=1)
    os.replace(tmp, p)


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def stock_price(h, symbol):
    p = C.price_path(h, symbol)
    if not os.path.exists(p):
        return None, None
    rows = C.read_prices(p)
    return (rows[-1]["close"], rows[-1]["date"]) if rows else (None, None)


def staleness(asof):
    """' (STALE: 12 days old)' when a price is more than 5 days old, else ''."""
    try:
        days = (dt.date.today() - dt.date.fromisoformat(asof)).days
    except (TypeError, ValueError):
        return ""
    return " (STALE: %d days old, refresh with pkdata.py)" % days if days > 5 else ""


def find_fund(h, name):
    date, funds = fund_rows(h)
    exact = [f for f in funds if f["fund"].lower() == name.lower()]
    hits = exact or [f for f in funds if name.lower() in f["fund"].lower()]
    if not hits:
        sys.exit("no fund matches %r in the %s MUFAP snapshot" % (name, date))
    if len(hits) > 1:
        sys.exit("%r matches %d funds; be more specific:\n  %s" % (
            name, len(hits), "\n  ".join(f["fund"] for f in hits[:15])))
    return hits[0]


def book(pf, entry):
    entry["time"] = now()
    pf["trades"].append(entry)


def do_buy(h, cfg, pf, symbol, qty, price=None, note=""):
    symbol = symbol.upper()
    px, asof = (price, "given") if price else stock_price(h, symbol)
    if px is None:
        raise ValueError("no price for %s: run `pkdata.py psx %s` or pass --price" % (symbol, symbol))
    lot = int(cfg.get("lot_size") or 1)
    qty = int(qty) // lot * lot
    if qty <= 0:
        raise ValueError("quantity rounds to zero with lot size %d" % lot)
    gross = qty * px
    fee = gross * cfg["cost_bps_per_side"] / 10000.0
    if gross + fee > pf["cash"] + 1e-6:
        raise ValueError("not enough cash: need %s, have %s" % (C.fmt_pkr(gross + fee), C.fmt_pkr(pf["cash"])))
    pos = pf["positions"].setdefault(symbol, {"kind": "stock", "qty": 0, "cost": 0.0})
    pos["qty"] += qty
    pos["cost"] += gross + fee
    pf["cash"] -= gross + fee
    book(pf, {"side": "buy", "symbol": symbol, "qty": qty, "price": px, "price_date": asof,
              "fee": round(fee, 2), "note": note})
    return "BUY  %s %d @ %.2f (%s)%s fee %s" % (symbol, qty, px, asof, staleness(asof), C.fmt_pkr(fee))


def do_sell(h, cfg, pf, symbol, qty, price=None, note=""):
    symbol = symbol.upper()
    pos = pf["positions"].get(symbol)
    if not pos or pos.get("kind") != "stock" or pos["qty"] <= 0:
        raise ValueError("no %s shares to sell (no short selling in this account)" % symbol)
    qty = pos["qty"] if str(qty).lower() == "all" else min(int(qty), pos["qty"])
    px, asof = (price, "given") if price else stock_price(h, symbol)
    if px is None:
        raise ValueError("no price for %s: pass --price" % symbol)
    gross = qty * px
    fee = gross * cfg["cost_bps_per_side"] / 10000.0
    cost_part = pos["cost"] * qty / pos["qty"]
    pnl = gross - fee - cost_part
    pos["qty"] -= qty
    pos["cost"] -= cost_part
    if pos["qty"] == 0:
        del pf["positions"][symbol]
    pf["cash"] += gross - fee
    book(pf, {"side": "sell", "symbol": symbol, "qty": qty, "price": px, "price_date": asof,
              "fee": round(fee, 2), "realized": round(pnl, 2), "note": note})
    return "SELL %s %d @ %.2f (%s)%s fee %s, realised %s" % (symbol, qty, px, asof, staleness(asof),
                                                          C.fmt_pkr(fee), C.fmt_pkr(pnl))


def cmd_init(a, h, cfg):
    if os.path.exists(ppath(h)) and not a.force:
        sys.exit("an account already exists; use --force to wipe it and start over")
    cash = float(a.cash or cfg["paper_starting_cash"])
    bench_px, bench_date = stock_price(h, cfg["benchmark"])
    pf = {"created": now(), "starting_cash": cash, "cash": cash, "positions": {}, "trades": [],
          "benchmark": {"symbol": cfg["benchmark"], "start_price": bench_px, "start_date": bench_date}}
    save(h, pf)
    print("paper account opened with %s" % C.fmt_pkr(cash))
    return 0


def cmd_buy(a, h, cfg):
    pf = load(h)
    try:
        print(do_buy(h, cfg, pf, a.symbol, a.qty, a.price, a.note or ""))
    except ValueError as e:
        sys.exit(str(e))
    save(h, pf)
    return 0


def cmd_sell(a, h, cfg):
    pf = load(h)
    try:
        print(do_sell(h, cfg, pf, a.symbol, a.qty, a.price, a.note or ""))
    except ValueError as e:
        sys.exit(str(e))
    save(h, pf)
    return 0


def cmd_invest(a, h, cfg):
    pf = load(h)
    f = find_fund(h, a.fund)
    amount = float(a.amount)
    if amount > pf["cash"] + 1e-6:
        sys.exit("not enough cash: %s available" % C.fmt_pkr(pf["cash"]))
    fee = amount * a.fee_pct / 100.0
    units = (amount - fee) / f["nav"]
    key = "FUND:" + f["fund"]
    pos = pf["positions"].setdefault(key, {"kind": "fund", "fund": f["fund"], "category": f["category"],
                                            "units": 0.0, "cost": 0.0})
    pos["units"] += units
    pos["cost"] += amount
    pf["cash"] -= amount
    book(pf, {"side": "invest", "fund": f["fund"], "amount": amount, "nav": f["nav"],
              "nav_date": f["validity_date"], "units": round(units, 4), "fee": round(fee, 2)})
    save(h, pf)
    print("INVEST %s in %s: %.4f units @ NAV %.4f (%s)" % (C.fmt_pkr(amount), f["fund"], units, f["nav"], f["validity_date"]))
    return 0


def cmd_redeem(a, h, cfg):
    pf = load(h)
    f = find_fund(h, a.fund)
    key = "FUND:" + f["fund"]
    pos = pf["positions"].get(key)
    if not pos:
        sys.exit("you hold no units of %s" % f["fund"])
    value = pos["units"] * f["nav"]
    amount = value if str(a.amount).lower() == "all" else min(float(a.amount), value)
    units = amount / f["nav"]
    fee = amount * a.fee_pct / 100.0
    cost_part = pos["cost"] * units / pos["units"]
    pnl = amount - fee - cost_part
    pos["units"] -= units
    pos["cost"] -= cost_part
    if pos["units"] < 1e-6:
        del pf["positions"][key]
    pf["cash"] += amount - fee
    book(pf, {"side": "redeem", "fund": f["fund"], "amount": round(amount, 2), "nav": f["nav"],
              "nav_date": f["validity_date"], "units": round(units, 4), "fee": round(fee, 2),
              "realized": round(pnl, 2)})
    save(h, pf)
    print("REDEEM %s from %s @ NAV %.4f, realised %s" % (C.fmt_pkr(amount), f["fund"], f["nav"], C.fmt_pkr(pnl)))
    return 0


def valuation(h, cfg, pf):
    navs = {}
    try:
        _, funds = fund_rows(h)
        navs = {f["fund"]: f for f in funds}
    except SystemExit:
        pass
    lines, total = [], pf["cash"]
    for key, pos in sorted(pf["positions"].items()):
        if pos["kind"] == "stock":
            px, asof = stock_price(h, key)
            qty = pos["qty"]
            label = "%s x%d" % (key, qty)
        else:
            f = navs.get(pos["fund"])
            px, asof = (f["nav"], f["validity_date"]) if f else (None, None)
            qty = pos["units"]
            label = "%s (%.2f units)" % (pos["fund"], qty)
        value = qty * px if px is not None else pos["cost"]
        total += value
        lines.append([label, "%.2f" % px if px is not None else "n/a", asof or "no price",
                      C.fmt_pkr(value), C.fmt_pct(value / pos["cost"] - 1 if pos["cost"] else None)])
    return lines, total


def cmd_status(a, h, cfg):
    pf = load(h)
    lines, total = valuation(h, cfg, pf)
    start = pf["starting_cash"]
    print("Paper account (opened %s)" % pf["created"])
    if lines:
        print(C.md_table(["Holding", "Price", "As of", "Value", "P/L"], lines))
    realized = sum(t.get("realized", 0) for t in pf["trades"])
    print("\nCash %s | Total %s | Return %s | Realised %s" % (
        C.fmt_pkr(pf["cash"]), C.fmt_pkr(total), C.fmt_pct(total / start - 1), C.fmt_pkr(realized)))
    b = pf.get("benchmark") or {}
    bpx, bdate = stock_price(h, b.get("symbol") or cfg["benchmark"])
    if b.get("start_price") and bpx:
        print("%s since %s: %s" % (b["symbol"], b["start_date"], C.fmt_pct(bpx / b["start_price"] - 1)))
    return 0


def cmd_log(a, h, cfg):
    pf = load(h)
    for t in pf["trades"][-a.last:]:
        print(json.dumps(t))
    return 0


def current_signals(h, cfg, strategy, symbols):
    """{symbol: 1/0} for what the strategy wants to hold as of the latest close."""
    want = {}
    if strategy == "momentum":
        # Same rule as `backtest.py momentum`: top 3 by 126-session return, positive only.
        scores = []
        for s in symbols:
            p = C.price_path(h, s)
            if os.path.exists(p):
                cl = [x["close"] for x in C.read_prices(p)]
                if len(cl) > 126 and cl[-127]:
                    scores.append((cl[-1] / cl[-127] - 1, s))
        scores.sort(reverse=True)
        top = {s for m, s in scores[:3] if m > 0}
        return {s: (1 if s in top else 0) for s in symbols}, None
    for s in symbols:
        p = C.price_path(h, s)
        if not os.path.exists(p):
            continue
        rows = C.read_prices(p)
        closes = [r["close"] for r in rows]
        sig = B.STRATEGIES[strategy](closes)
        # replay so stateful signals (breakout, rsi) carry their last opinion forward
        state = 0
        for i in range(len(closes)):
            v = sig(i)
            if v is not None:
                state = v
        want[s] = state
    return want, None


def cmd_signals(a, h, cfg):
    pf = load(h)
    symbols = [s.upper() for s in (a.symbols or cfg["watchlist"])]
    want, _ = current_signals(h, cfg, a.strategy, symbols)
    longs = sorted(s for s, v in want.items() if v == 1)
    # Signals manage stocks only: fund holdings are left alone and not counted as spendable.
    stock_value = sum(p["qty"] * (stock_price(h, k)[0] or 0) for k, p in pf["positions"].items()
                      if p["kind"] == "stock")
    budget = (pf["cash"] + stock_value) * a.invest_pct / 100.0
    per = budget / len(longs) if longs else 0
    orders = []
    for s in sorted(want):
        px, _ = stock_price(h, s)
        have = pf["positions"].get(s, {}).get("qty", 0)
        target = int(per / px) if (s in longs and px) else 0
        lot = int(cfg.get("lot_size") or 1)
        target = target // lot * lot
        if want[s] == 1 and have > 0 and not a.resize:
            continue  # already long: leave it unless asked to resize
        if target != have:
            orders.append((s, target - have))
    print("%s signals: long %s" % (a.strategy, ", ".join(longs) or "nothing"))
    if not orders:
        print("no orders needed")
        return 0
    for s, d in orders:
        print("  %s %s %d" % ("BUY " if d > 0 else "SELL", s, abs(d)))
    if not a.apply:
        print("\nNothing booked. Rerun with --apply to place these in the paper account.")
        return 0
    for s, d in sorted(orders, key=lambda o: o[1]):  # sells first to free cash
        try:
            msg = (do_buy if d > 0 else do_sell)(h, cfg, pf, s, abs(d), None, "signal:" + a.strategy)
            print(msg)
        except ValueError as e:
            print("skipped %s: %s" % (s, e))
    save(h, pf)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--cash", type=float)
    p.add_argument("--force", action="store_true")
    for n in ("buy", "sell"):
        p = sub.add_parser(n)
        p.add_argument("symbol")
        p.add_argument("qty")
        p.add_argument("--price", type=float)
        p.add_argument("--note")
    for n in ("invest", "redeem"):
        p = sub.add_parser(n)
        p.add_argument("fund")
        p.add_argument("amount")
        p.add_argument("--fee-pct", type=float, default=0.0)
    sub.add_parser("status")
    p = sub.add_parser("log")
    p.add_argument("--last", type=int, default=20)
    p = sub.add_parser("signals")
    p.add_argument("--strategy", default="sma", choices=["sma", "breakout", "rsi", "momentum"])
    p.add_argument("--symbols", nargs="*")
    p.add_argument("--invest-pct", type=float, default=90.0, help="share of account value to deploy")
    p.add_argument("--resize", action="store_true", help="also resize positions already held")
    p.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"init": cmd_init, "buy": cmd_buy, "sell": cmd_sell, "invest": cmd_invest,
            "redeem": cmd_redeem, "status": cmd_status, "log": cmd_log,
            "signals": cmd_signals}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
