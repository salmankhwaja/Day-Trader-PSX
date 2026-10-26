#!/usr/bin/env python3
"""psx-broker: from an approved order to a ticket you type into your broker's app, and back into
your ledger once it fills. It never sends an order: PSX retail apps (Finqalab, AKD, KTrade...) have
no public order API, and this tool wouldn't use one if they did.

  broker.py show                         the tickets: READY (passed psx-risk, unchanged since) or not
  broker.py filled E1 --price 203.70     you placed E1 in your app and it filled: record it
  broker.py filled E1 --price 203.70 --qty 500 --time 10:41 --commission 76.40
  broker.py flatten                      a day trade still open near the close: the SELL tickets
  broker.py today                        what was filled today, and what's still open

How a trade goes:
  psx-exit (plan) -> psx-timemachine (odds) -> psx-budget (size) -> psx-risk (PASS/BLOCK)
  -> broker.py show -> you type the ticket into your app -> broker.py filled -> psx-alerts watch it
A ticket is READY only when psx-risk passed that exact order (same symbol, side, type, quantity and
prices: a fingerprint is compared). Change anything and it must be checked again.

Recording a fill writes the trade into your portfolio ledger (portfolio.py), with the stop from
the bracket, so advice, the dashboard and GREEN/RED see it. Charges are estimated from your broker's
schedule unless you give them from the contract note.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402


def status(h):
    """[(order, verdict-or-None, ready, why)] for the orders on file."""
    doc = desk.read(h, "orders.json", {}) or {}
    verdicts = {v["id"]: v for v in (desk.read(h, "risk.json", {}) or {}).get("verdicts", [])}
    out = []
    for o in doc.get("orders", []):
        v = verdicts.get(o["id"])
        if not v:
            out.append((o, None, False, "not checked yet: run psx-risk (risk.py check)"))
        elif v["fingerprint"] != desk.fingerprint(o):
            out.append((o, v, False, "changed since psx-risk checked it: check again"))
        elif v["verdict"] != "PASS":
            out.append((o, v, False, "BLOCKED: " + "; ".join(v["reasons"])))
        else:
            out.append((o, v, True, "; ".join(v.get("warnings") or []) or "passed psx-risk"))
    return doc, out


def validity(h, broker):
    import portfolio as PF
    b = PF.load(h)["brokers"].get(broker or "") or {}
    return {"day": "today only: place it again each morning while you hold"}.get(b.get("stop_validity"),
                                                                                 "check how long your app keeps it")


def ticket_text(o, broker_note):
    if o["type"] == "stop-loss":
        how = "STOP-LOSS: trigger %.2f, limit %.2f (%s)" % (o["trigger"], o["limit"], broker_note)
    elif o["type"] == "limit":
        how = "LIMIT %.2f" % o["limit"]
    else:
        how = "MARKET"
    when = " after the buy fills" if o.get("parent") else ""
    return "%s %s %d %s, %s%s%s" % (o["id"], o["side"], o["qty"], o["symbol"], how, when,
                                    " (optional take-profit)" if o.get("optional") else "")


def cmd_show(a, h, cfg):
    doc, st = status(h)
    if not st:
        print("No orders on file: psx-budget writes them (budget.py --write).")
        return 0
    broker = doc.get("broker")
    print("TICKETS for your %s app (nothing is sent from here)" % (broker or "broker's"))
    for o, v, ready, why in st:
        print("  [%s] %s" % ("READY" if ready else "NOT READY", ticket_text(o, validity(h, broker))))
        print("          %s" % why)
    plan = doc.get("plan") or {}
    if plan.get("flat_by"):
        print("  Day trade: be out by %s. psx-alerts can ring then (alerts.py add --from-plan)." % plan["flat_by"])
    print("After it fills: broker.py filled E1 --price PRICE (it goes into your portfolio ledger).")
    print(desk.DISCLAIMER)
    tk = desk.read(h, "tickets.json", {}) or {}
    tk.setdefault("shown", []).append({"at": desk.now(a.now).isoformat(timespec="minutes"),
                                       "ready": [o["id"] for o, _, r, _ in st if r]})
    desk.write(h, "tickets.json", tk)
    return 0


def cmd_filled(a, h, cfg):
    import portfolio as PF
    doc, st = status(h)
    row = next(((o, v, r, w) for o, v, r, w in st if o["id"].upper() == a.id.upper()), None)
    if not row:
        sys.exit("no order %s on file (broker.py show lists them)" % a.id)
    o, v, ready, why = row
    is_exit = o["side"] == "SELL"
    if not ready and not is_exit and not a.force:
        sys.exit("%s isn't READY (%s). If you really placed it, add --force; it'll be recorded as unchecked." % (o["id"], why))
    now = desk.now(a.now)
    qty = a.qty or o["qty"]
    lg = PF.load(h)
    broker = a.broker or doc.get("broker") or lg.get("default_broker")
    stop = next((x["trigger"] for x in doc.get("orders", []) if x.get("parent") == o["id"] and x.get("role") == "stop"), None)
    try:
        e = PF.record_trade(lg, o["side"].lower(), o["symbol"], qty, a.price, broker, now.date().isoformat(),
                            a.commission, a.taxes, a.other, "psx-broker %s (%s)" % (o["id"], o.get("role")),
                            stop if not is_exit else None, a.time or now.strftime("%H:%M"))
    except ValueError as err:
        sys.exit(str(err))
    PF.save(h, lg)
    tk = desk.read(h, "tickets.json", {}) or {}
    tk.setdefault("fills", []).append({"id": o["id"], "role": o.get("role"), "symbol": o["symbol"], "side": o["side"],
                                       "qty": qty, "price": a.price, "date": now.date().isoformat(),
                                       "time": e.get("time"), "style": (doc.get("plan") or {}).get("style"),
                                       "checked": ready, "ledger_id": e["id"]})
    desk.write(h, "tickets.json", tk)
    print("recorded " + PF.describe(e))
    if not is_exit and stop:
        print("stop-loss %.2f saved with the holding. Place ticket %s-SL in your app now%s." % (
            stop, o["id"], "; it lasts one day" if "today only" in validity(h, broker) else ""))
    return 0


def open_day_trades(h, today):
    tk = desk.read(h, "tickets.json", {}) or {}
    pos = {}
    for f in tk.get("fills", []):
        if f.get("date") != today or f.get("style") != "day":
            continue
        pos[f["symbol"]] = pos.get(f["symbol"], 0) + (f["qty"] if f["side"] == "BUY" else -f["qty"])
    return {s: q for s, q in pos.items() if q > 0}


def cmd_flatten(a, h, cfg):
    now = desk.now(a.now)
    pos = open_day_trades(h, now.date().isoformat())
    if not pos:
        print("No day trades open today. Nothing to flatten.")
        return 0
    orders = [{"id": "X%d" % (i + 1), "role": "exit", "symbol": s, "side": "SELL", "type": "market", "qty": q,
               "style": "day"} for i, (s, q) in enumerate(sorted(pos.items()))]
    for o in orders:
        o["fingerprint"] = desk.fingerprint(o)
    desk.write(h, "orders.json", {"made": now.isoformat(timespec="minutes"), "plan": {"style": "day"}, "orders": orders,
                                  "broker": (desk.read(h, "orders.json", {}) or {}).get("broker")})
    import risk as R
    res = R.check_orders(h, cfg, orders, now)
    desk.write(h, "risk.json", {"made": now.isoformat(timespec="minutes"), "verdicts": res})
    print("FLATTEN: sell what's left of today's day trades (exits are always allowed)")
    for o in orders:
        print("  " + ticket_text(o, ""))
    print("Cancel their open stop-loss and take-profit orders in your app first, so nothing sells twice.")
    print("Then: broker.py filled X1 --price PRICE")
    return 0


def cmd_today(a, h, cfg):
    today = desk.now(a.now).date().isoformat()
    tk = desk.read(h, "tickets.json", {}) or {}
    fills = [f for f in tk.get("fills", []) if f.get("date") == today]
    if not fills:
        print("No fills recorded today.")
        return 0
    print(C.md_table(["Time", "Order", "Side", "Stock", "Qty", "Price", "Checked"],
                     [[f.get("time") or "", f["id"], f["side"], f["symbol"], f["qty"], "%.2f" % f["price"],
                       "yes" if f.get("checked") else "NO"] for f in fills]))
    pos = open_day_trades(h, today)
    if pos:
        print("Day trades still open: %s. Flat by the close: broker.py flatten." % ", ".join("%s %d" % kv for kv in pos.items()))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show")
    p.add_argument("--now")
    p = sub.add_parser("filled")
    p.add_argument("id")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--qty", type=int)
    p.add_argument("--time", help="HH:MM it filled (default: now)")
    p.add_argument("--broker")
    p.add_argument("--commission", type=float)
    p.add_argument("--taxes", type=float)
    p.add_argument("--other", type=float)
    p.add_argument("--force", action="store_true", help="record an entry that didn't pass psx-risk")
    p.add_argument("--now")
    p = sub.add_parser("flatten")
    p.add_argument("--now")
    p = sub.add_parser("today")
    p.add_argument("--now")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"show": cmd_show, "filled": cmd_filled, "flatten": cmd_flatten, "today": cmd_today}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
