#!/usr/bin/env python3
"""Your real PSX portfolio: every trade, which broker, what it cost, and what it made.

This is a record-keeper and adviser. It never talks to a broker and never places an order.

  portfolio.py broker presets          published tariffs of PSX brokers (brokers.json, with sources)
  portfolio.py broker add NAME --preset akd [--default]          a broker from a preset
  portfolio.py broker add NAME --commission-pct 0.15 --per-share 0.03 [--min-commission X]
                               [--sales-tax-pct 13] [--default]  or by hand, from your commission sheet
  portfolio.py broker import [akd,js-global,...]                 load presets as brokers
  portfolio.py broker list
  portfolio.py buy  SYMBOL QTY PRICE --broker NAME [--date YYYY-MM-DD] [--commission X]
                                     [--taxes X] [--other X] [--stop X] [--note TEXT]
  portfolio.py sell SYMBOL QTY|all PRICE --broker NAME [same options]
  portfolio.py fund-buy "FUND" AMOUNT [--nav X] [--load-pct X] [--date]   record a mutual fund investment
  portfolio.py fund-sell "FUND" AMOUNT|all [--nav X] [--load-pct X]       record a redemption
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
import freshness as F  # noqa: E402
import psxinfo as P  # noqa: E402


# ------------------------------------------------------------------ storage

def lpath(h):
    return os.path.join(h, "portfolio", "ledger.json")


def load(h):
    p = lpath(h)
    if not os.path.exists(p):
        return {"version": 1, "brokers": {}, "default_broker": None, "entries": [], "stops": {}, "next_id": 1}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(h, lg):
    p = lpath(h)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
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


def check_time(t):
    """HH:MM (24-hour, Pakistan time) or None."""
    if t in (None, ""):
        return None
    try:
        return dt.datetime.strptime(str(t).strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise ValueError("time must be HH:MM (24-hour), got %r" % t)


def pk_now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=5)


def check_date(s):
    try:
        return dt.date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise ValueError("date must be YYYY-MM-DD, got %r" % s)


# ------------------------------------------------------------------ fees

PRESETS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brokers.json")


def load_presets(path=None):
    with open(path or PRESETS_FILE, encoding="utf-8") as f:
        return json.load(f)


def preset_broker(key, path=None):
    """A broker fee schedule from brokers.json, with the file's statutory defaults filled in."""
    data = load_presets(path)
    bk = data["brokers"].get(key.lower())
    if not bk:
        raise ValueError("no preset %r; choose from: %s" % (key, ", ".join(sorted(data["brokers"]))))
    b = {k: v for k, v in data.get("_defaults", {}).items() if k in ("sales_tax_pct", "cvt_pct", "cdc_per_share", "levies_pct")}
    b.update({k: v for k, v in bk.items() if k not in ("name", "confidence", "source")})
    b.update({"preset": key.lower(), "full_name": bk.get("name"), "source": bk.get("source"),
              "confidence": bk.get("confidence"), "as_of": data.get("_as_of")})
    return b


def tiers_of(b):
    """The commission tiers of a broker record (older records stored flat commission_pct/per_share)."""
    if b.get("tiers"):
        return b["tiers"]
    return [{"max_price": None, "per_share": float(b.get("per_share", 0.03 if "commission_pct" not in b else 0.0)),
             "pct": float(b.get("commission_pct", 0.15))}]


def estimate_charges(broker, qty, price, side="buy"):
    """(commission, taxes, other) for a trade, from a broker's schedule. See brokers.json _model."""
    b = broker or {}
    value = qty * price
    tier = None
    for t in tiers_of(b):
        tier = t
        if t.get("max_price") is not None and price <= float(t["max_price"]):
            break
    commission = max(qty * float(tier.get("per_share") or 0), value * float(tier.get("pct") or 0) / 100.0,
                     float(b.get("min_commission") or 0))
    taxes = commission * float(b.get("sales_tax_pct") or 0) / 100.0
    if side == "buy":
        taxes += value * float(b.get("cvt_pct") or 0) / 100.0
    other = qty * float(b.get("cdc_per_share") or 0) + value * float(b.get("levies_pct") or 0) / 100.0
    other += value * float(b.get("other_pct") or 0) / 100.0  # older records
    return round(commission, 2), round(taxes, 2), round(other, 2)


def estimate_commission(broker, qty, price, side="buy"):
    """(commission, taxes + other) -- kept for callers that want two numbers."""
    c, t, o = estimate_charges(broker, qty, price, side)
    return c, round(t + o, 2)


def resolve_broker(lg, name):
    name = name or lg.get("default_broker")
    if not name:
        raise ValueError("which broker? pass --broker NAME (add one first: portfolio.py broker add NAME --preset akd)")
    for k in lg["brokers"]:
        if k.lower() == name.lower():
            return k
    b = preset_broker("psx-minimum")
    b["auto_added"] = True
    lg["brokers"][name] = b
    return name


def record_trade(lg, side, symbol, qty, price, broker, date=None, commission=None, taxes=None, other=None, note="",
                 stop=None, time=None):
    symbol = symbol.upper()
    broker = resolve_broker(lg, broker)
    date = check_date(date or today())
    time = check_time(time)
    if time is None and date == pk_now().date().isoformat():
        time = pk_now().strftime("%H:%M")  # recorded today without a time: the time you recorded it
    qty, price = int(qty), float(price)
    if qty <= 0 or price <= 0:
        raise ValueError("quantity and price must be positive")
    b = lg["brokers"][broker]
    est_c, est_t, est_o = estimate_charges(b, qty, price, side)
    if commission is not None and taxes is None:  # sales tax follows the commission actually charged
        est_t = round(float(commission) * float(b.get("sales_tax_pct") or 0) / 100.0 +
                      (qty * price * float(b.get("cvt_pct") or 0) / 100.0 if side == "buy" else 0), 2)
    estimated = [k for k, v in (("commission", commission), ("taxes", taxes), ("other", other)) if v is None]
    e = {"type": side, "date": date, "time": time, "symbol": symbol, "qty": qty, "price": price, "broker": broker,
         "commission": round(float(est_c if commission is None else commission), 2),
         "taxes": round(float(est_t if taxes is None else taxes), 2),
         "other": round(float(est_o if other is None else other), 2),
         "commission_estimated": "commission" in estimated, "estimated": estimated, "note": note or ""}
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
    if stop is not None and side == "buy":
        if float(stop) >= price:
            raise ValueError("a stop-loss must be below the buy price")
        lg["stops"][symbol] = float(stop)
    return e


# ------------------------------------------------------------------ lots and P/L

def ordered(entries):
    return sorted(entries, key=lambda e: (e["date"], e.get("time") or "", e["id"]))


def lots(lg):
    """FIFO lots per (symbol, broker) and the list of realised sales, replaying the ledger in date order."""
    book, sales = {}, []
    for e in ordered(lg["entries"]):
        if e["type"] == "buy":
            fees = e["commission"] + e["taxes"] + e["other"]
            book.setdefault((e["symbol"], e["broker"]), []).append({
                "qty": e["qty"], "date": e["date"], "time": e.get("time"),
                "unit_cost": (e["qty"] * e["price"] + fees) / e["qty"], "price": e["price"], "id": e["id"]})
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


def status_of(net):
    """GREEN: selling now would make money after every charge. RED: it would lose. FLAT: neither."""
    if net is None:
        return None
    return "GREEN" if net > 0.005 else "RED" if net < -0.005 else "FLAT"


def holdings(h, lg):
    """Open positions, each compared with what you paid: when you bought (date and time) against the
    price now (live, or the last close) and when that price is from, after selling charges."""
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
                                        "first_buy_time": l.get("time"), "lots": []})
            p["qty"] += l["qty"]
            p["cost"] += l["qty"] * l["unit_cost"]
            p["brokers"][broker] = p["brokers"].get(broker, 0) + l["qty"]
            if (l["date"], l.get("time") or "") < (p["first_buy"], p["first_buy_time"] or ""):
                p["first_buy"], p["first_buy_time"] = l["date"], l.get("time")
            p["lots"].append(dict(l, broker=broker))
    out = []
    for sym, p in sorted(by_sym.items()):
        rows = C.read_prices(C.price_path(h, sym)) if os.path.exists(C.price_path(h, sym)) else []
        px = rows[-1]["close"] if rows else None
        live = bool(rows and rows[-1].get("live"))
        p["avg_cost"] = p["cost"] / p["qty"]
        p["price"], p["price_date"] = px, (rows[-1]["date"] if rows else None)
        p["price_source"] = "live" if live else ("close" if rows else None)
        p["price_time"] = ((C.LIVE.get("fetched") or "")[11:16] or None) if live else (C.CLOSE_TIME if rows else None)
        p["value"] = p["qty"] * px if px else None
        p["unrealised"] = p["value"] - p["cost"] if px else None
        p["unrealised_pct"] = (p["value"] / p["cost"] - 1) if px and p["cost"] else None
        net = 0.0 if px else None
        for l in p["lots"]:
            l["cost"] = round(l["qty"] * l["unit_cost"], 2)
            if px:
                sell = sum(estimate_charges(lg["brokers"].get(l["broker"]), l["qty"], px, "sell"))
                l["net_pl"] = round(l["qty"] * px - sell - l["cost"], 2)
                l["net_pl_pct"] = l["net_pl"] / l["cost"] if l["cost"] else None
                net += l["net_pl"]
            else:
                l["net_pl"] = l["net_pl_pct"] = None
            l["status"] = status_of(l["net_pl"])
        p["lots"].sort(key=lambda l: (l["date"], l.get("time") or ""))
        p["net_pl"] = round(net, 2) if net is not None else None
        p["net_pl_pct"] = p["net_pl"] / p["cost"] if net is not None and p["cost"] else None
        p["status"] = status_of(p["net_pl"])
        p["dividends"] = round(divs.get(sym, 0), 2)
        p["days_held"] = (dt.date.today() - dt.date.fromisoformat(p["first_buy"])).days
        out.append(p)
    return out


def latest_navs(h):
    """{fund name: snapshot row} from the newest MUFAP snapshot, or {}."""
    try:
        import rank
        _, rows = rank.fund_rows(h)
        return {r["fund"]: r for r in rows}
    except SystemExit:
        return {}


def find_fund_name(h, name, lg=None):
    """Exact or unique partial match against MUFAP funds and funds already in the ledger."""
    names = set(latest_navs(h))
    if lg:
        names |= {e["fund"] for e in lg["entries"] if e["type"] in ("fund_buy", "fund_sell")}
    exact = [n for n in names if n.lower() == name.lower()]
    hits = exact or [n for n in names if name.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    raise ValueError("%r matches %d funds; be more specific:\n  %s" % (name, len(hits), "\n  ".join(sorted(hits)[:15])))


def fund_holdings(h, lg):
    """Units, average cost and value per fund (average-cost method), plus realised redemptions."""
    navs = latest_navs(h)
    pos, realised = {}, []
    for e in ordered(lg["entries"]):
        if e["type"] == "fund_buy":
            p = pos.setdefault(e["fund"], {"fund": e["fund"], "units": 0.0, "cost": 0.0, "first_buy": e["date"],
                                           "category": e.get("category")})
            p["units"] += e["units"]
            p["cost"] += e["amount"]
        elif e["type"] == "fund_sell":
            p = pos.get(e["fund"])
            if not p or p["units"] <= 1e-9:
                continue
            cost = p["cost"] * min(e["units"], p["units"]) / p["units"]
            p["units"] -= e["units"]
            p["cost"] -= cost
            realised.append({"id": e["id"], "date": e["date"], "fund": e["fund"], "proceeds": e["amount"],
                             "cost": round(cost, 2), "pnl": round(e["amount"] - cost, 2)})
    out = []
    for f, p in sorted(pos.items()):
        if p["units"] <= 1e-6:
            continue
        snap = navs.get(f)
        nav = snap["nav"] if snap else None
        p.update(avg_nav=p["cost"] / p["units"], nav=nav, nav_date=snap["validity_date"] if snap else None,
                 category=p.get("category") or (snap or {}).get("category"),
                 value=round(p["units"] * nav, 2) if nav else None)
        p["unrealised"] = round(p["value"] - p["cost"], 2) if nav else None
        p["unrealised_pct"] = (p["value"] / p["cost"] - 1) if nav and p["cost"] else None
        out.append(p)
    return out, realised


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
        elif t == "fund_buy":
            bal -= e["amount"]
        elif t == "fund_sell":
            bal += e["amount"]
    return round(bal, 2)


def summary(h, lg):
    hs = holdings(h, lg)
    _, sales = lots(lg)
    fees = sum(e.get("commission", 0) + e.get("taxes", 0) + e.get("other", 0)
               for e in lg["entries"] if e["type"] in ("buy", "sell"))
    divs = sum(e["net"] for e in lg["entries"] if e["type"] == "dividend")
    funds, fund_sales = fund_holdings(h, lg)
    value = sum(p["value"] or p["cost"] for p in hs) + sum(f["value"] or f["cost"] for f in funds)
    cost = sum(p["cost"] for p in hs) + sum(f["cost"] for f in funds)
    return {"holdings": hs, "funds": funds, "sales": sales, "fund_sales": fund_sales,
            "value": round(value, 2), "cost": round(cost, 2), "unrealised": round(value - cost, 2),
            "realised": round(sum(s["pnl"] for s in sales) + sum(s["pnl"] for s in fund_sales), 2),
            "dividends": round(divs, 2), "fees": round(fees, 2), "cash": cash_balance(lg)}


# ------------------------------------------------------------------ commands

def tier_text(b):
    parts = []
    for t in tiers_of(b):
        rate = " or ".join(x for x in ("Rs %g/share" % t["per_share"] if t.get("per_share") else "",
                                      "%g%%" % t["pct"] if t.get("pct") else "") if x)
        rate += ", whichever higher" if t.get("per_share") and t.get("pct") else ""
        parts.append(("up to Rs %g: " % t["max_price"] if t.get("max_price") is not None else
                      ("above: " if len(tiers_of(b)) > 1 else "")) + rate)
    if b.get("min_commission"):
        parts.append("min Rs %g/trade" % b["min_commission"])
    return "; ".join(parts)


def extra_text(b):
    """Fees outside the per-trade model, and what the broker's app lets you set up, when known."""
    bits = []
    if b.get("monthly_fee"):
        bits.append("Rs %g/month" % b["monthly_fee"])
    if b.get("account_opening_fee"):
        bits.append("Rs %g once (account)" % b["account_opening_fee"])
    if b.get("stop_validity"):
        bits.append("stop-loss orders: %s" % ("today only" if b["stop_validity"] == "day" else b["stop_validity"]))
    return ", ".join(bits)


def charge_text(b):
    return "sales tax %g%% of commission, CDC Rs %g/share, levies %g%%%s" % (
        float(b.get("sales_tax_pct") or 0), float(b.get("cdc_per_share") or 0), float(b.get("levies_pct") or 0),
        ", CVT %g%% on buys" % b["cvt_pct"] if b.get("cvt_pct") else "")


def cmd_broker(a, h, cfg):
    lg = load(h)
    if a.action == "presets":
        data = load_presets(a.file)
        rows = [[k, v["name"], tier_text(v), extra_text(v), v.get("confidence", "")[:60]] for k, v in sorted(data["brokers"].items())]
        print(C.md_table(["Preset", "Broker", "Commission", "Other fees, orders", "Basis"], rows))
        print("\nPass-through charges applied to every preset: " + charge_text(data.get("_defaults", {})))
        print("Source notes and links: %s (as of %s). Your signed commission sheet wins: edit the file or "
              "add a broker by hand." % (a.file or PRESETS_FILE, data.get("_as_of")))
        return 0
    if a.action == "import":
        data = load_presets(a.file)
        keys = [k.strip().lower() for k in a.name.split(",")] if a.name else sorted(data["brokers"])
        try:
            for k in keys:
                lg["brokers"][k] = preset_broker(k, a.file)
        except ValueError as e:
            sys.exit(str(e))
        if not lg.get("default_broker") and len(keys) == 1:
            lg["default_broker"] = keys[0]
        save(h, lg)
        print("imported %d broker schedules: %s" % (len(keys), ", ".join(keys)))
        print("Set the one you use as default: portfolio.py broker add KEY --preset KEY --default")
        return 0
    if a.action == "list" or not a.name:
        if not lg["brokers"]:
            print("no brokers yet. See the presets (portfolio.py broker presets), then e.g.\n"
                  "  portfolio.py broker add AKD --preset akd --default")
            return 0
        rows = [[n + (" (default)" if n == lg.get("default_broker") else ""), tier_text(b), charge_text(b),
                 b.get("preset") or "custom"] for n, b in sorted(lg["brokers"].items())]
        print(C.md_table(["Broker", "Commission", "Other charges", "From"], rows))
        return 0
    # add / update
    try:
        b = preset_broker(a.preset, a.file) if a.preset else dict(lg["brokers"].get(a.name) or preset_broker("psx-minimum"))
    except ValueError as e:
        sys.exit(str(e))
    if a.commission_pct is not None or a.per_share is not None:
        b["tiers"] = [{"max_price": None, "per_share": a.per_share if a.per_share is not None else 0.0,
                       "pct": a.commission_pct if a.commission_pct is not None else 0.0}]
        b.pop("commission_pct", None)
        b.pop("per_share", None)
        b["preset"] = None
    for k in ("min_commission", "sales_tax_pct", "cdc_per_share", "levies_pct", "cvt_pct"):
        v = getattr(a, k)
        if v is not None:
            b[k] = v
    b.pop("auto_added", None)
    lg["brokers"][a.name] = b
    if a.default or not lg.get("default_broker"):
        lg["default_broker"] = a.name
    save(h, lg)
    print("broker %s: %s | %s%s" % (a.name, tier_text(b), charge_text(b),
                                    " | default" if lg["default_broker"] == a.name else ""))
    ex = estimate_charges(b, 1000, 100.0, "buy")
    print("example: buying 1,000 shares at Rs 100 costs about Rs %s in commission, %s in taxes, %s other" % ex)
    return 0


def describe(e):
    if e["type"] in ("buy", "sell"):
        fees = e["commission"] + e["taxes"] + e["other"]
        est = e.get("estimated") or (["commission"] if e.get("commission_estimated") else [])
        return "#%d %s %s %s %d @ %.2f via %s, charges PKR %s (commission %s, taxes %s, other %s)%s" % (
            e["id"], e["date"] + (" " + e["time"] if e.get("time") else ""), e["type"].upper(), e["symbol"], e["qty"], e["price"], e["broker"],
            "{:,.2f}".format(fees), "{:,.2f}".format(e["commission"]), "{:,.2f}".format(e["taxes"]),
            "{:,.2f}".format(e["other"]), " [estimated: %s]" % ", ".join(est) if est else "")
    if e["type"] in ("fund_buy", "fund_sell"):
        return "#%d %s %s %s %.4f units @ NAV %.4f = PKR %s%s" % (
            e["id"], e["date"], "FUND BUY" if e["type"] == "fund_buy" else "FUND SELL", e["fund"], e["units"], e["nav"],
            "{:,.2f}".format(e["amount"]), " (load %.2f%%)" % e["load_pct"] if e.get("load_pct") else "")
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
        e = record_trade(lg, a.cmd, a.symbol, qty, a.price, a.broker, a.date, a.commission, a.taxes, a.other, a.note,
                         getattr(a, "stop", None), a.time)
    except ValueError as err:
        sys.exit(str(err))
    save(h, lg)
    print("recorded " + describe(e))
    if a.cmd == "buy":
        own = lg["stops"].get(e["symbol"])
        print("stop-loss: %s" % ("%.2f (yours)" % own if own is not None else
                                 "computed daily by `portfolio.py advise` (set your own: portfolio.py stop %s PRICE)" % e["symbol"]))
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


def cmd_fund(a, h, cfg):
    lg = load(h)
    try:
        name = find_fund_name(h, a.fund, lg)
    except ValueError as e:
        sys.exit(str(e))
    if not name:
        if a.nav is None:
            sys.exit("no MUFAP fund matches %r: run pkdata.py mufap, or give --nav to record it anyway" % a.fund)
        name = a.fund
    snap = latest_navs(h).get(name)
    nav = a.nav if a.nav is not None else (snap or {}).get("nav")
    if not nav:
        sys.exit("no NAV for %s: pass --nav" % name)
    date = check_date(a.date or today())
    load_pct = float(a.load_pct or 0)
    if a.cmd == "fund-buy":
        amount = float(a.amount)
        units = amount * (1 - load_pct / 100.0) / nav
        e = add_entry(lg, {"type": "fund_buy", "date": date, "fund": name, "amount": round(amount, 2), "nav": nav,
                           "units": round(units, 4), "load_pct": load_pct, "category": (snap or {}).get("category"),
                           "nav_estimated": a.nav is None, "note": a.note or ""})
    else:
        funds, _ = fund_holdings(h, lg)
        held = next((f for f in funds if f["fund"] == name), None)
        if not held:
            sys.exit("you hold no units of %s" % name)
        units = held["units"] if str(a.amount).lower() == "all" else min(float(a.amount) / nav, held["units"])
        amount = units * nav * (1 - load_pct / 100.0)
        e = add_entry(lg, {"type": "fund_sell", "date": date, "fund": name, "amount": round(amount, 2), "nav": nav,
                           "units": round(units, 4), "load_pct": load_pct, "nav_estimated": a.nav is None,
                           "note": a.note or ""})
    save(h, lg)
    print("recorded " + describe(e) + (" (NAV of %s from MUFAP; pass --nav for your actual price)" % (snap or {}).get("validity_date")
                                         if a.nav is None else ""))
    return 0


def cmd_cash(a, h, cfg):
    lg = load(h)
    amt = float(a.amount) * (1 if a.action == "deposit" else -1)
    e = add_entry(lg, {"type": "cash", "date": check_date(a.date or today()), "amount": amt,
                       "broker": a.broker or lg.get("default_broker"), "note": a.note or ""})
    save(h, lg)
    print("recorded %s; cash now %s" % (describe(e), C.fmt_pkr(cash_balance(lg))))
    return 0


def paint(word, ok_tty=None):
    """GREEN / RED in colour on a terminal, with an arrow so it reads without colour too."""
    if not word:
        return "n/a"
    tty = sys.stdout.isatty() if ok_tty is None else ok_tty
    mark = {"GREEN": "\u25b2 GREEN", "RED": "\u25bc RED", "FLAT": "= FLAT"}[word]
    if tty and os.environ.get("NO_COLOR") is None:
        code = {"GREEN": "32", "RED": "31", "FLAT": "33"}[word]
        return "\033[1;%sm%s\033[0m" % (code, mark)
    return mark


def when(date, time):
    return date + (" " + time if time else "") if date else "n/a"


def cmd_holdings(a, h, cfg):
    import advice as A
    lg = load(h)
    if any(e["type"] == "buy" for e in lg["entries"]):
        F.decide(a, h, cfg, sorted({e["symbol"] for e in lg["entries"] if e["type"] == "buy"}), payouts=False)
    s = summary(h, lg)
    if not s["holdings"] and not s["funds"]:
        print("no holdings recorded. Start with: portfolio.py buy SYMBOL QTY PRICE --broker NAME --date YYYY-MM-DD")
        return 0
    stops = {r["symbol"]: r for r in A.review_holdings(h, cfg, lg, s)}
    rows = []
    for p in s["holdings"]:
        st = stops.get(p["symbol"], {})
        rows.append([p["symbol"], paint(p["status"]),
                     "%.2f on %s" % (p["avg_cost"], when(p["first_buy"], p["first_buy_time"])) + (" (%d buys)" % len(p["lots"]) if len(p["lots"]) > 1 else ""),
                     "n/a" if p["price"] is None else "%.2f %s %s" % (p["price"], "live at" if p["price_source"] == "live" else "close of",
                                                                       when(p["price_date"], p["price_time"])),
                     p["qty"], C.fmt_pkr(p["value"]),
                     "n/a" if p["net_pl"] is None else "%s%s (%s)" % ("+" if p["net_pl"] >= 0 else "-", C.fmt_pkr(abs(p["net_pl"])), C.fmt_pct(p["net_pl_pct"])),
                     "n/a" if st.get("stop") is None else "%.2f%s" % (st["stop"], "*" if st.get("stop_source") == "yours" else ""),
                     ", ".join("%s %d" % kv for kv in sorted(p["brokers"].items()))])
    if rows:
        print(C.md_table(["Stock", "Status", "Bought (avg cost incl. charges, first buy)", "Now", "Qty", "Value",
                          "P/L if sold now", "Stop", "Broker"], rows))
        g = sum(1 for p in s["holdings"] if p["status"] == "GREEN")
        r = sum(1 for p in s["holdings"] if p["status"] == "RED")
        print("%d in profit (GREEN), %d at a loss (RED), after buying and selling charges." % (g, r))
    if a.lots and s["holdings"]:
        print("\nEACH PURCHASE vs NOW")
        print(C.md_table(["Stock", "Bought on", "Broker", "Qty", "Paid (incl. charges)", "Now", "P/L if sold now", "Status"],
                         [[p["symbol"], when(l["date"], l.get("time")), l["broker"], l["qty"], "%.2f" % l["unit_cost"],
                           "n/a" if p["price"] is None else "%.2f" % p["price"],
                           "n/a" if l["net_pl"] is None else "%s%s (%s)" % ("+" if l["net_pl"] >= 0 else "-", C.fmt_pkr(abs(l["net_pl"])), C.fmt_pct(l["net_pl_pct"])),
                           paint(l["status"])] for p in s["holdings"] for l in p["lots"]]))
    if s["funds"]:
        print("\nMUTUAL FUNDS")
        print(C.md_table(["Fund", "Status", "Category", "Units", "Avg NAV", "NAV", "Value", "Unrealised", "%"],
                         [[f["fund"], paint(status_of(f["unrealised"])), f.get("category") or "", "%.4f" % f["units"], "%.4f" % f["avg_nav"],
                           "n/a" if f["nav"] is None else "%.4f (%s)" % (f["nav"], f["nav_date"]), C.fmt_pkr(f["value"]),
                           C.fmt_pkr(f["unrealised"]), C.fmt_pct(f["unrealised_pct"])] for f in s["funds"]]))
    print("\nInvested %s | Value %s | Unrealised %s | Realised %s | Dividends %s | Fees paid %s%s" % (
        C.fmt_pkr(s["cost"]), C.fmt_pkr(s["value"]), C.fmt_pkr(s["unrealised"]), C.fmt_pkr(s["realised"]),
        C.fmt_pkr(s["dividends"]), C.fmt_pkr(s["fees"]), "" if s["cash"] is None else " | Cash " + C.fmt_pkr(s["cash"])))
    print("GREEN / RED: what selling everything at the price now would make or lose against what you paid, "
          "after the charges on both sides. Times are Pakistan time; an end-of-day price is stamped %s, the close. "
          "* = a stop you set yourself. --lots shows every purchase." % C.CLOSE_TIME)
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
    _, fsales = fund_holdings(h, lg)
    if a.year:
        fsales = [x for x in fsales if x["date"].startswith(str(a.year))]
    if fsales:
        print("\nFund redemptions:")
        print(C.md_table(["Date", "Fund", "Proceeds", "Cost", "P/L"],
                         [[x["date"], x["fund"], C.fmt_pkr(x["proceeds"]), C.fmt_pkr(x["cost"]), C.fmt_pkr(x["pnl"])]
                          for x in fsales]))
    tot = sum(x["pnl"] for x in sales) + sum(x["pnl"] for x in fsales)
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


FIELDS = ["date", "side", "symbol", "qty", "price", "broker", "commission", "taxes", "other", "note", "stop", "time"]


def cmd_import(a, h, cfg):
    lg = load(h)
    n, errors = 0, []
    with open(a.file, newline="", encoding="utf-8") as f:
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
                         r.get("date"), num("commission"), num("taxes"), num("other"), r.get("note", ""),
                         num("stop") if side == "buy" else None, r.get("time") or None)
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
    with open(a.file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for e in ordered(lg["entries"]):
            if e["type"] in ("buy", "sell"):
                w.writerow([e["date"], e["type"], e["symbol"], e["qty"], e["price"], e["broker"], e["commission"],
                            e["taxes"], e["other"], e.get("note", ""), "", e.get("time") or ""])
    print("wrote " + a.file)
    return 0


def cmd_advise(a, h, cfg):
    import advice as A
    return A.cmd_advise(a, h, cfg)


def cmd_orders(a, h, cfg):
    import advice as A
    return A.cmd_orders(a, h, cfg)


def cmd_check(a, h, cfg):
    import advice as A
    return A.cmd_check(a, h, cfg)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("broker", help="add / list brokers and their charges; presets of published tariffs")
    p.add_argument("action", choices=["add", "list", "presets", "import"])
    p.add_argument("name", nargs="?", help="add: your name for the broker; import: comma list of preset keys")
    p.add_argument("--preset", help="start from a published tariff in brokers.json (see: broker presets)")
    p.add_argument("--file", help="a brokers.json of your own instead of the bundled one")
    p.add_argument("--commission-pct", type=float, help="percent of trade value")
    p.add_argument("--per-share", type=float, help="rupees per share (the higher of the two applies)")
    p.add_argument("--min-commission", type=float, help="minimum rupees per trade")
    p.add_argument("--sales-tax-pct", type=float, help="sales tax on commission, e.g. 13 (Sindh)")
    p.add_argument("--cdc-per-share", type=float)
    p.add_argument("--levies-pct", type=float, help="PSX + regulator levies, percent of value")
    p.add_argument("--cvt-pct", type=float, help="capital value tax on purchases, percent")
    p.add_argument("--default", action="store_true")
    for side in ("buy", "sell"):
        p = sub.add_parser(side)
        p.add_argument("symbol")
        p.add_argument("qty")
        p.add_argument("price", type=float)
        p.add_argument("--broker")
        p.add_argument("--date")
        p.add_argument("--time", help="HH:MM, Pakistan time (default: now, when the date is today)")
        p.add_argument("--commission", type=float)
        p.add_argument("--taxes", type=float, help="taxes on the contract note (sales tax on commission, CVT, CGT)")
        p.add_argument("--other", type=float, help="other charges (CDC, NCCPL, exchange and regulator levies)")
        p.add_argument("--note")
        if side == "buy":
            p.add_argument("--stop", type=float, help="your own stop-loss for this holding (default: computed)")
    for n in ("fund-buy", "fund-sell"):
        p = sub.add_parser(n, help="record a mutual fund investment / redemption")
        p.add_argument("fund", help="fund name or a unique part of it, as on MUFAP")
        p.add_argument("amount", help="rupees invested; for fund-sell rupees to redeem, or 'all'")
        p.add_argument("--nav", type=float, help="the NAV you actually got (default: latest MUFAP NAV)")
        p.add_argument("--load-pct", type=float, help="front-end (buy) or back-end (sell) load, percent")
        p.add_argument("--date")
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
    p = sub.add_parser("holdings", help="each holding: bought (date, time, price) vs now (live or close): GREEN or RED")
    p.add_argument("--lots", action="store_true", help="also every purchase on its own")
    F.add_args(p)
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
    p.add_argument("--candidates", type=int, help="default: your risk profile's 'candidates'")
    p.add_argument("--json", action="store_true")
    F.add_args(p)
    p = sub.add_parser("orders", help="order tickets for your broker's app: stop-losses, buys, sells")
    p.add_argument("--all", action="store_true", help="buy ideas from the whole market")
    p.add_argument("--shariah", action="store_true")
    p.add_argument("--buy", type=int, default=3)
    p.add_argument("--json", action="store_true")
    F.add_args(p)
    p = sub.add_parser("check", help="one share: verdict, stop, target, size and the price calculator")
    p.add_argument("symbol")
    p.add_argument("--entry", type=float, help="the price you'd pay (default: last close)")
    p.add_argument("--stop", type=float, help="your own stop (default: computed from your style)")
    p.add_argument("--capital", type=float, help="size against this instead of your recorded portfolio")
    p.add_argument("--json", action="store_true")
    F.add_args(p)
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    fn = {"broker": cmd_broker, "buy": cmd_trade, "sell": cmd_trade, "dividend": cmd_dividend,
          "dividends": cmd_dividends, "cash": cmd_cash, "holdings": cmd_holdings, "pnl": cmd_pnl, "fees": cmd_fees,
          "trades": cmd_trades, "delete": cmd_delete, "stop": cmd_stop, "import": cmd_import, "export": cmd_export,
          "advise": cmd_advise, "check": cmd_check, "orders": cmd_orders, "fund-buy": cmd_fund, "fund-sell": cmd_fund}[a.cmd]
    return fn(a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
