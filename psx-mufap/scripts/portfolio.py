#!/usr/bin/env python3
"""Your real PSX portfolio: every trade, which broker, what it cost, and what it made.

This is a record-keeper and adviser. It never talks to a broker and never places an order.

  portfolio.py broker add NAME [--commission-pct 0.15] [--min-commission 0] [--per-share 0]
                               [--other-pct 0] [--default]       a broker's fee schedule
  portfolio.py broker list
  portfolio.py buy  SYMBOL QTY PRICE --broker NAME [--date YYYY-MM-DD] [--commission X]
                                     [--taxes X] [--other X] [--note TEXT]
  portfolio.py sell SYMBOL QTY|all PRICE --broker NAME [same options]
  portfolio.py dividend SYMBOL NET [--gross X] [--tax X] [--date]  record a dividend you received
  portfolio.py dividends [--apply]      find dividends due on your holdings from PSX book closures
  portfolio.py cash deposit|withdraw AMOUNT [--broker NAME] [--date]   optional cash tracking
  portfolio.py holdings                 positions, average cost incl. fees, value, unrealised P/L, stop
  portfolio.py pnl [--year 2026]        realised P/L per sale (FIFO), dividends, fees
  portfolio.py fees                     commissions, taxes and other charges by broker
  portfolio.py trades [--symbol X]      the ledger; each entry has an id
  portfolio.py delete ID                remove a mistaken entry
  portfolio.py stop SYMBOL PRICE|auto   set your own stop-loss for a holding, or go back to the computed one
  portfolio.py import FILE.csv          bulk-load trades: date,side,symbol,qty,price,broker[,commission,taxes,other,note]
  portfolio.py export FILE.csv
  portfolio.py advise [--all] [--shariah] [--buy 3]   sell / hold / buy suggestions with stop-losses

Costs. Give the actual charges from your broker's contract note with --commission, --taxes
(e.g. CVT, SST on commission) and --other (CDC, NCCPL, SECP fees). Leave --commission out and it
is estimated from the broker's schedule (and flagged "estimated"). Every charge is added to the
cost of a buy and taken off the proceeds of a sale, so profit and loss are always after costs.

Lots. Shares are held at a broker, so sales consume that broker's lots first-in, first-out.
Realised P/L, holding period and fees are kept per sale. Capital gains tax depends on your
filer status and holding period; record it with --taxes on the sale if you want it in the P/L.

Data: <home>/portfolio/ledger.json (home = ~/pkmarket or $PKM_HOME). It is your financial
record: back it up, keep it private, never commit it to a public repo.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import psxinfo as P  # noqa: E402


# ------------------------------------------------------------------ storage

def lpath(h):
    return os.path.join(h, "portfolio", "ledger.json")


def load(h):
    p = lpath(h)
    if not os.path.exists(p):
        return {"version": 1, "brokers": {}, "default_broker": None, "entries": [], "stops": {}, "next_id": 1}
    with open(p) as f:
        return json.load(f)


def save(h, lg):
    p = lpath(h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(lg, f, indent=1)
    os.replace(tmp, p)


def add_entry(lg, e):
    e["id"] = lg["next_id"]
    lg["next_id"] += 1
    e["recorded"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lg["entries"].append(e)
    return e


def today():
    return dt.date.today().isoformat()


def check_date(s):
    try:
        return dt.date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise ValueError("date must be YYYY-MM-DD, got %r" % s)


# ------------------------------------------------------------------ fees

def estimate_commission(broker, qty, price):
    b = broker or {}
    value = qty * price
    c = max(value * float(b.get("commission_pct", 0.15)) / 100.0,
            qty * float(b.get("per_share", 0.0)),
            float(b.get("min_commission", 0.0)))
    other = value * float(b.get("other_pct", 0.0)) / 100.0
    return round(c, 2), round(other, 2)


def resolve_broker(lg, name):
    name = name or lg.get("default_broker")
    if not name:
        raise ValueError("which broker? pass --broker NAME (add one first: portfolio.py broker add NAME)")
    for k in lg["brokers"]:
        if k.lower() == name.lower():
            return k
    lg["brokers"][name] = {"commission_pct": 0.15, "min_commission": 0.0, "per_share": 0.0,
                           "other_pct": 0.0, "auto_added": True}
    return name


def record_trade(lg, side, symbol, qty, price, broker, date=None, commission=None, taxes=0.0, other=None, note=""):
    symbol = symbol.upper()
    broker = resolve_broker(lg, broker)
    date = check_date(date or today())
    qty, price = int(qty), float(price)
    if qty <= 0 or price <= 0:
        raise ValueError("quantity and price must be positive")
    est_c, est_o = estimate_commission(lg["brokers"][broker], qty, price)
    estimated = commission is None
    e = {"type": side, "date": date, "symbol": symbol, "qty": qty, "price": price, "broker": broker,
         "commission": round(float(est_c if commission is None else commission), 2),
         "taxes": round(float(taxes or 0), 2),
         "other": round(float(est_o if other is None else other), 2),
         "commission_estimated": estimated, "note": note or ""}
    add_entry(lg, e)
    _, sales = lots(lg)  # replay: no sale, this one or a later one, may sell shares not held then
    bad = next((x for x in sales if x["unmatched"]), None)
    if bad:
        lg["entries"].remove(e)
        lg["next_id"] -= 1
        book, _ = lots(lg)
        held = sum(l["qty"] for l in book.get((symbol, broker), []))
        raise ValueError("that would sell %s shares not held at %s on %s (held now: %d; no short selling)" % (
            bad["symbol"], bad["broker"], bad["date"], held))
    return e


# ------------------------------------------------------------------ lots and P/L

def ordered(entries):
    return sorted(entries, key=lambda e: (e["date"], e["id"]))


def lots(lg):
    """FIFO lots per (symbol, broker) and the list of realised sales, replaying the ledger in date order."""
    book, sales = {}, []
    for e in ordered(lg["entries"]):
        if e["type"] == "buy":
            fees = e["commission"] + e["taxes"] + e["other"]
            book.setdefault((e["symbol"], e["broker"]), []).append({
                "qty": e["qty"], "date": e["date"], "unit_cost": (e["qty"] * e["price"] + fees) / e["qty"],
                "price": e["price"], "id": e["id"]})
        elif e["type"] == "sell":
            q = book.get((e["symbol"], e["broker"]), [])
            fees = e["commission"] + e["taxes"] + e["other"]
            proceeds = e["qty"] * e["price"] - fees
            need, cost, days_w = e["qty"], 0.0, 0.0
            while need > 0 and q:
                lot = q[0]
                take = min(need, lot["qty"])
                cost += take * lot["unit_cost"]
                days_w += take * (dt.date.fromisoformat(e["date"]) - dt.date.fromisoformat(lot["date"])).days
                lot["qty"] -= take
                need -= take
                if lot["qty"] == 0:
                    q.pop(0)
            sold = e["qty"] - need
            sales.append({"id": e["id"], "date": e["date"], "symbol": e["symbol"], "broker": e["broker"],
                          "qty": sold, "price": e["price"], "proceeds": round(proceeds, 2), "cost": round(cost, 2),
                          "fees": round(fees, 2), "pnl": round(proceeds - cost, 2),
                          "pnl_pct": (proceeds / cost - 1) if cost else None,
                          "avg_days_held": round(days_w / sold) if sold else None, "unmatched": need})
    return book, sales


def holdings(h, lg):
    book, _ = lots(lg)
    divs = {}
    for e in lg["entries"]:
        if e["type"] == "dividend":
            divs[e["symbol"]] = divs.get(e["symbol"], 0) + e["net"]
    by_sym = {}
    for (sym, broker), ls in book.items():
        for l in ls:
            if l["qty"] <= 0:
                continue
            p = by_sym.setdefault(sym, {"symbol": sym, "qty": 0, "cost": 0.0, "brokers": {}, "first_buy": l["date"],
                                        "lots": []})
            p["qty"] += l["qty"]
            p["cost"] += l["qty"] * l["unit_cost"]
            p["brokers"][broker] = p["brokers"].get(broker, 0) + l["qty"]
            p["first_buy"] = min(p["first_buy"], l["date"])
            p["lots"].append(dict(l, broker=broker))
    out = []
    for sym, p in sorted(by_sym.items()):
        rows = C.read_prices(C.price_path(h, sym)) if os.path.exists(C.price_path(h, sym)) else []
        px = rows[-1]["close"] if rows else None
        p["avg_cost"] = p["cost"] / p["qty"]
        p["price"], p["price_date"] = px, (rows[-1]["date"] if rows else None)
        p["value"] = p["qty"] * px if px else None
        p["unrealised"] = p["value"] - p["cost"] if px else None
        p["unrealised_pct"] = (p["value"] / p["cost"] - 1) if px and p["cost"] else None
        p["dividends"] = round(divs.get(sym, 0), 2)
        p["days_held"] = (dt.date.today() - dt.date.fromisoformat(p["first_buy"])).days
        out.append(p)
    return out


def cash_balance(lg):
    """Deposits - withdrawals - buys + sales + dividends; None when no deposit was ever recorded."""
    if not any(e["type"] == "cash" for e in lg["entries"]):
        return None
    bal = 0.0
    for e in lg["entries"]:
        t = e["type"]
        if t == "cash":
            bal += e["amount"]
        elif t == "buy":
            bal -= e["qty"] * e["price"] + e["commission"] + e["taxes"] + e["other"]
        elif t == "sell":
            bal += e["qty"] * e["price"] - e["commission"] - e["taxes"] - e["other"]
        elif t == "dividend":
            bal += e["net"]
    return round(bal, 2)


def summary(h, lg):
    hs = holdings(h, lg)
    _, sales = lots(lg)
    fees = sum(e.get("commission", 0) + e.get("taxes", 0) + e.get("other", 0)
               for e in lg["entries"] if e["type"] in ("buy", "sell"))
    divs = sum(e["net"] for e in lg["entries"] if e["type"] == "dividend")
    value = sum(p["value"] or p["cost"] for p in hs)
    cost = sum(p["cost"] for p in hs)
    return {"holdings": hs, "sales": sales, "value": round(value, 2), "cost": round(cost, 2),
            "unrealised": round(value - cost, 2), "realised": round(sum(s["pnl"] for s in sales), 2),
            "dividends": round(divs, 2), "fees": round(fees, 2), "cash": cash_balance(lg)}


# ------------------------------------------------------------------ commands

def cmd_broker(a, h, cfg):
    lg = load(h)
    if a.action == "list" or not a.name:
        if not lg["brokers"]:
            print("no brokers yet: portfolio.py broker add NAME --commission-pct 0.15")
            return 0
        rows = [[n + (" (default)" if n == lg.get("default_broker") else ""), b.get("commission_pct"),
                 b.get("min_commission"), b.get("per_share"), b.get("other_pct")] for n, b in sorted(lg["brokers"].items())]
        print(C.md_table(["Broker", "Commission %", "Minimum PKR", "Per share PKR", "Other %"], rows))
        return 0
    b = lg["brokers"].setdefault(a.name, {})
    for k in ("commission_pct", "min_commission", "per_share", "other_pct"):
        v = getattr(a, k)
        if v is not None:
            b[k] = v
        b.setdefault(k, {"commission_pct": 0.15}.get(k, 0.0))
    b.pop("auto_added", None)
    if a.default or not lg.get("default_broker"):
        lg["default_broker"] = a.name
    save(h, lg)
    print("broker %s: commission %s%% (min PKR %s, per share %s), other %s%%%s" % (
        a.name, b["commission_pct"], b["min_commission"], b["per_share"], b["other_pct"],
        ", default" if lg["default_broker"] == a.name else ""))
    return 0


def describe(e):
    if e["type"] in ("buy", "sell"):
        fees = e["commission"] + e["taxes"] + e["other"]
        return "#%d %s %s %s %d @ %.2f via %s, fees PKR %s%s" % (
            e["id"], e["date"], e["type"].upper(), e["symbol"], e["qty"], e["price"], e["broker"],
            "{:,.2f}".format(fees), " (commission estimated)" if e.get("commission_estimated") else "")
    if e["type"] == "dividend":
        return "#%d %s DIVIDEND %s net PKR %s" % (e["id"], e["date"], e["symbol"], "{:,.2f}".format(e["net"]))
    return "#%d %s CASH %s PKR %s" % (e["id"], e["date"], e.get("broker") or "", "{:,.2f}".format(e["amount"]))


def cmd_trade(a, h, cfg):
    lg = load(h)
    try:
        qty = a.qty
        if a.cmd == "sell" and str(qty).lower() == "all":
            book, _ = lots(lg)
            broker = resolve_broker(lg, a.broker)
            qty = sum(l["qty"] for l in book.get((a.symbol.upper(), broker), []))
            if not qty:
                raise ValueError("no %s held at %s" % (a.symbol.upper(), broker))
        e = record_trade(lg, a.cmd, a.symbol, qty, a.price, a.broker, a.date, a.commission, a.taxes, a.other, a.note)
    except ValueError as err:
        sys.exit(str(err))
    save(h, lg)
    print("recorded " + describe(e))
    if a.cmd == "sell":
        _, sales = lots(lg)
        s = next(x for x in sales if x["id"] == e["id"])
        print("realised %s (%s) after all costs, held about %s days" % (
            C.fmt_pkr(s["pnl"]), C.fmt_pct(s["pnl_pct"]), s["avg_days_held"]))
    return 0


def cmd_dividend(a, h, cfg):
    lg = load(h)
    net = float(a.net)
    e = add_entry(lg, {"type": "dividend", "date": check_date(a.date or today()), "symbol": a.symbol.upper(),
                       "net": net, "gross": float(a.gross) if a.gross else None,
                       "tax": float(a.tax) if a.tax else None, "note": a.note or ""})
    save(h, lg)
    print("recorded " + describe(e))
    return 0


def due_dividends(h, cfg, lg, on=None):
    """Cash dividends and bonus issues whose book closure fell while you held the shares, not yet
    recorded. Entitlement uses the holding 2 days before book closure (T+2 settlement)."""
    on = on or dt.date.today()
    recorded = {(e["symbol"], e.get("ref")) for e in lg["entries"] if e["type"] in ("dividend", "bonus")}
    market = P.load_payouts(h)
    out = []
    for sym in sorted({e["symbol"] for e in lg["entries"] if e["type"] == "buy"}):
        c = P.load_company(h, sym) or {}
        seen = set()
        for p in list(c.get("payouts") or []) + [x for x in market if x["symbol"] == sym]:
            ref = "%s|%s" % (p.get("announced"), p.get("details"))
            bc = p.get("bc_from")
            if ref in seen or (sym, ref) in recorded or not bc or bc > on.isoformat():
                continue
            seen.add(ref)
            if not (p.get("cash_pct") or p.get("bonus_pct")):
                continue
            cutoff = (dt.date.fromisoformat(bc) - dt.timedelta(days=2)).isoformat()
            held = sum(e["qty"] * (1 if e["type"] == "buy" else -1) for e in lg["entries"]
                       if e.get("symbol") == sym and e["type"] in ("buy", "sell") and e["date"] < cutoff)
            if held <= 0:
                continue
            fv = P.face_value(cfg, sym)
            gross = held * fv * (p.get("cash_pct") or 0) / 100.0
            tax = gross * float(cfg.get("dividend_tax", 0.15))
            out.append({"symbol": sym, "ref": ref, "details": p.get("details"), "book_closure": bc, "qty": held,
                        "gross": round(gross, 2), "tax": round(tax, 2), "net": round(gross - tax, 2),
                        "bonus_shares": int(held * (p.get("bonus_pct") or 0) / 100.0)})
    return out


def cmd_dividends(a, h, cfg):
    lg = load(h)
    due = due_dividends(h, cfg, lg)
    if not due:
        print("no unrecorded dividends or bonus issues on your holdings")
        return 0
    for d in due:
        print("%-8s %-16s book closure %s on %d shares: about PKR %s net (tax %s)%s" % (
            d["symbol"], d["details"], d["book_closure"], d["qty"], "{:,.0f}".format(d["net"]),
            "{:,.0f}".format(d["tax"]), ", +%d bonus shares" % d["bonus_shares"] if d["bonus_shares"] else ""))
    if not a.apply:
        print("\nNot recorded. Check the amounts against what your broker credited, then rerun with --apply, "
              "or record the exact figure with: portfolio.py dividend SYMBOL NET")
        return 0
    for d in due:
        if d["net"]:
            add_entry(lg, {"type": "dividend", "date": d["book_closure"], "symbol": d["symbol"], "net": d["net"],
                           "gross": d["gross"], "tax": d["tax"], "ref": d["ref"], "estimated": True})
        if d["bonus_shares"]:  # bonus shares arrive at zero cost, at the broker holding most of the shares
            book, _ = lots(lg)
            brokers = {b: sum(l["qty"] for l in ls) for (s, b), ls in book.items() if s == d["symbol"]}
            br = max(brokers, key=brokers.get) if brokers else resolve_broker(lg, None)
            add_entry(lg, {"type": "buy", "date": d["book_closure"], "symbol": d["symbol"], "qty": d["bonus_shares"],
                           "price": 0.0, "broker": br, "commission": 0.0, "taxes": 0.0, "other": 0.0,
                           "commission_estimated": False, "note": "bonus issue " + d["details"], "ref": d["ref"]})
            add_entry(lg, {"type": "bonus", "date": d["book_closure"], "symbol": d["symbol"], "ref": d["ref"],
                           "qty": d["bonus_shares"]})
    save(h, lg)
    print("recorded %d entitlements (marked estimated)" % len(due))
    return 0


def cmd_cash(a, h, cfg):
    lg = load(h)
    amt = float(a.amount) * (1 if a.action == "deposit" else -1)
    e = add_entry(lg, {"type": "cash", "date": check_date(a.date or today()), "amount": amt,
                       "broker": a.broker or lg.get("default_broker"), "note": a.note or ""})
    save(h, lg)
    print("recorded %s; cash now %s" % (describe(e), C.fmt_pkr(cash_balance(lg))))
    return 0


def cmd_holdings(a, h, cfg):
    import advice as A
    lg = load(h)
    s = summary(h, lg)
    if not s["holdings"]:
        print("no holdings recorded. Start with: portfolio.py buy SYMBOL QTY PRICE --broker NAME --date YYYY-MM-DD")
        return 0
    stops = {r["symbol"]: r for r in A.review_holdings(h, cfg, lg, s)}
    rows = []
    for p in s["holdings"]:
        st = stops.get(p["symbol"], {})
        rows.append([p["symbol"], p["qty"], "%.2f" % p["avg_cost"], "n/a" if p["price"] is None else "%.2f" % p["price"],
                     C.fmt_pkr(p["value"]), C.fmt_pkr(p["unrealised"]), C.fmt_pct(p["unrealised_pct"]),
                     "n/a" if st.get("stop") is None else "%.2f%s" % (st["stop"], "*" if st.get("stop_source") == "yours" else ""),
                     ", ".join("%s %d" % kv for kv in sorted(p["brokers"].items())), p["first_buy"]])
    print(C.md_table(["Stock", "Qty", "Avg cost", "Price", "Value", "Unrealised", "%", "Stop", "Broker", "Since"], rows))
    print("\nInvested %s | Value %s | Unrealised %s | Realised %s | Dividends %s | Fees paid %s%s" % (
        C.fmt_pkr(s["cost"]), C.fmt_pkr(s["value"]), C.fmt_pkr(s["unrealised"]), C.fmt_pkr(s["realised"]),
        C.fmt_pkr(s["dividends"]), C.fmt_pkr(s["fees"]), "" if s["cash"] is None else " | Cash " + C.fmt_pkr(s["cash"])))
    print("Average cost includes commission, taxes and fees. * = a stop you set yourself.")
    return 0


def cmd_pnl(a, h, cfg):
    lg = load(h)
    _, sales = lots(lg)
    if a.year:
        sales = [x for x in sales if x["date"].startswith(str(a.year))]
    divs = [e for e in lg["entries"] if e["type"] == "dividend" and (not a.year or e["date"].startswith(str(a.year)))]
    if sales:
        print(C.md_table(["Date", "Stock", "Broker", "Qty", "Price", "Proceeds", "Cost", "Fees", "P/L", "%", "Days"],
                         [[x["date"], x["symbol"], x["broker"], x["qty"], "%.2f" % x["price"], C.fmt_pkr(x["proceeds"]),
                           C.fmt_pkr(x["cost"]), C.fmt_pkr(x["fees"]), C.fmt_pkr(x["pnl"]), C.fmt_pct(x["pnl_pct"]),
                           x["avg_days_held"]] for x in sales]))
    else:
        print("no sales%s" % (" in %s" % a.year if a.year else ""))
    tot = sum(x["pnl"] for x in sales)
    dv = sum(e["net"] for e in divs)
    print("\nRealised P/L %s (after commission, taxes and fees) | Dividends %s | Total %s" % (
        C.fmt_pkr(tot), C.fmt_pkr(dv), C.fmt_pkr(tot + dv)))
    wins = [x for x in sales if x["pnl"] > 0]
    if sales:
        print("%d sales, %d profitable (%.0f%%)" % (len(sales), len(wins), 100.0 * len(wins) / len(sales)))
    return 0


def fee_table(lg):
    by = {}
    for e in lg["entries"]:
        if e["type"] not in ("buy", "sell") or "bonus issue" in (e.get("note") or ""):
            continue
        b = by.setdefault(e["broker"], {"trades": 0, "turnover": 0.0, "commission": 0.0, "taxes": 0.0, "other": 0.0,
                                         "estimated": 0})
        b["trades"] += 1
        b["turnover"] += e["qty"] * e["price"]
        b["commission"] += e["commission"]
        b["taxes"] += e["taxes"]
        b["other"] += e["other"]
        b["estimated"] += 1 if e.get("commission_estimated") else 0
    return by


def cmd_fees(a, h, cfg):
    by = fee_table(load(h))
    if not by:
        print("no trades recorded")
        return 0
    rows = []
    for k, b in sorted(by.items()):
        tot = b["commission"] + b["taxes"] + b["other"]
        rows.append([k, b["trades"], C.fmt_pkr(b["turnover"]), C.fmt_pkr(b["commission"]), C.fmt_pkr(b["taxes"]),
                     C.fmt_pkr(b["other"]), C.fmt_pkr(tot), "%.3f%%" % (100 * tot / b["turnover"]) if b["turnover"] else "-",
                     b["estimated"]])
    print(C.md_table(["Broker", "Trades", "Turnover", "Commission", "Taxes", "Other", "Total", "Cost/turnover", "Estimated"], rows))
    return 0


def cmd_trades(a, h, cfg):
    lg = load(h)
    for e in ordered(lg["entries"]):
        if a.symbol and e.get("symbol") != a.symbol.upper():
            continue
        print(describe(e) + ("  [%s]" % e["note"] if e.get("note") else ""))
    return 0


def cmd_delete(a, h, cfg):
    lg = load(h)
    e = next((x for x in lg["entries"] if x["id"] == a.id), None)
    if not e:
        sys.exit("no entry #%d" % a.id)
    lg["entries"].remove(e)
    try:  # removing a buy must not leave a later sale without shares
        _, sales = lots(lg)
        bad = [s for s in sales if s["unmatched"]]
        if bad:
            raise ValueError("deleting #%d would leave sale #%d without enough shares" % (a.id, bad[0]["id"]))
    except ValueError as err:
        sys.exit(str(err))
    save(h, lg)
    print("deleted " + describe(e))
    return 0


def cmd_stop(a, h, cfg):
    lg = load(h)
    sym = a.symbol.upper()
    if str(a.price).lower() == "auto":
        lg["stops"].pop(sym, None)
        msg = "%s: back to the computed stop" % sym
    else:
        lg["stops"][sym] = float(a.price)
        msg = "%s: your stop-loss is %.2f" % (sym, float(a.price))
    save(h, lg)
    print(msg)
    return 0


FIELDS = ["date", "side", "symbol", "qty", "price", "broker", "commission", "taxes", "other", "note"]


def cmd_import(a, h, cfg):
    lg = load(h)
    n, errors = 0, []
    with open(a.file, newline="") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (r.get("date") or "", 0 if (r.get("side") or "").lower() == "buy" else 1))
    for i, r in enumerate(rows, 2):
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        try:
            side = r["side"].lower()
            if side not in ("buy", "sell"):
                raise ValueError("side must be buy or sell")
            num = lambda k: float(r[k].replace(",", "")) if r.get(k) else None  # noqa: E731
            record_trade(lg, side, r["symbol"], int(float(r["qty"].replace(",", ""))), num("price"), r.get("broker"),
                         r.get("date"), num("commission"), num("taxes") or 0.0, num("other"), r.get("note", ""))
            n += 1
        except (KeyError, ValueError) as e:
            errors.append("line %d: %s" % (i, e))
    if errors and not a.partial:
        sys.exit("nothing imported; fix these first (or use --partial):\n  " + "\n  ".join(errors))
    save(h, lg)
    print("imported %d trades%s" % (n, "; skipped:\n  " + "\n  ".join(errors) if errors else ""))
    return 0


def cmd_export(a, h, cfg):
    lg = load(h)
    with open(a.file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for e in ordered(lg["entries"]):
            if e["type"] in ("buy", "sell"):
                w.writerow([e["date"], e["type"], e["symbol"], e["qty"], e["price"], e["broker"], e["commission"],
                            e["taxes"], e["other"], e.get("note", "")])
    print("wrote " + a.file)
    return 0


def cmd_advise(a, h, cfg):
    import advice as A
    return A.cmd_advise(a, h, cfg)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("broker")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("name", nargs="?")
    p.add_argument("--commission-pct", type=float)
    p.add_argument("--min-commission", type=float)
    p.add_argument("--per-share", type=float)
    p.add_argument("--other-pct", type=float)
    p.add_argument("--default", action="store_true")
    for side in ("buy", "sell"):
        p = sub.add_parser(side)
        p.add_argument("symbol")
        p.add_argument("qty")
        p.add_argument("price", type=float)
        p.add_argument("--broker")
        p.add_argument("--date")
        p.add_argument("--commission", type=float)
        p.add_argument("--taxes", type=float, default=0.0)
        p.add_argument("--other", type=float)
        p.add_argument("--note")
    p = sub.add_parser("dividend")
    p.add_argument("symbol")
    p.add_argument("net")
    p.add_argument("--gross")
    p.add_argument("--tax")
    p.add_argument("--date")
    p.add_argument("--note")
    p = sub.add_parser("dividends")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("cash")
    p.add_argument("action", choices=["deposit", "withdraw"])
    p.add_argument("amount", type=float)
    p.add_argument("--broker")
    p.add_argument("--date")
    p.add_argument("--note")
    sub.add_parser("holdings")
    p = sub.add_parser("pnl")
    p.add_argument("--year", type=int)
    sub.add_parser("fees")
    p = sub.add_parser("trades")
    p.add_argument("--symbol")
    p = sub.add_parser("delete")
    p.add_argument("id", type=int)
    p = sub.add_parser("stop")
    p.add_argument("symbol")
    p.add_argument("price")
    p = sub.add_parser("import")
    p.add_argument("file")
    p.add_argument("--partial", action="store_true", help="import the good rows even if some fail")
    p = sub.add_parser("export")
    p.add_argument("file")
    p = sub.add_parser("advise")
    p.add_argument("--all", action="store_true", help="look for buys across every liquid listed share")
    p.add_argument("--shariah", action="store_true", help="Shariah-compliant (KMI) buy ideas only")
    p.add_argument("--sector")
    p.add_argument("--buy", type=int, default=3, help="how many buy ideas (default 3)")
    p.add_argument("--candidates", type=int, default=15)
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    fn = {"broker": cmd_broker, "buy": cmd_trade, "sell": cmd_trade, "dividend": cmd_dividend,
          "dividends": cmd_dividends, "cash": cmd_cash, "holdings": cmd_holdings, "pnl": cmd_pnl, "fees": cmd_fees,
          "trades": cmd_trades, "delete": cmd_delete, "stop": cmd_stop, "import": cmd_import, "export": cmd_export,
          "advise": cmd_advise}[a.cmd]
    return fn(a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
