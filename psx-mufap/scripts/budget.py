#!/usr/bin/env python3
"""psx-budget: how many shares the plan can afford, so a stop-out costs no more than you decided.

  budget.py                               size the plan on file (trader/plan.json)
  budget.py --write                       ...and write the bracket to trader/orders.json
  budget.py --account 500000 --max-loss 2500 --write    your own numbers for this trade

The size is the smallest of:
  max loss / loss per share at the stop    max loss = risk_per_trade x capital (or --max-loss);
                                           the loss per share counts the charges both ways
  max_position_pct x capital / entry       no single share gets too big
  (cash - cash_reserve_pct x capital) / cost per share    never spend the reserve
in whole shares (lot_size), with charges from your default broker's schedule (portfolio.py broker).
Capital is your portfolio plus recorded cash (portfolio.py cash deposit), or --account.

It writes one bracket, the way PSX apps take it:
  BUY  limit at the entry
  SELL stop-loss: trigger at the stop, limit stop_limit_gap below (so it fills in a fast fall)
  SELL limit at the target (optional: your app may not let both sell orders hold the same shares)
psx-risk checks it next, psx-broker turns it into tickets you type into your app.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402


def size(h, cfg, plan, account=None, max_loss=None):
    import portfolio as PF
    import advice as A
    lg = PF.load(h)
    broker = plan.get("broker") or lg.get("default_broker")
    b = lg["brokers"].get(broker) if broker else None
    cap, cash = (float(account), float(account)) if account else desk.capital(h, cfg)
    if not cap:
        raise ValueError("no capital known: record cash (portfolio.py cash deposit AMOUNT) or pass --account")
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    lot = int(cfg.get("lot_size") or 1)
    ml = float(max_loss) if max_loss else desk.setting(cfg, "risk_per_trade") * cap

    def loss_per_share(q):
        return entry - stop + (sum(PF.estimate_charges(b, q, entry, "buy")) + sum(PF.estimate_charges(b, q, stop, "sell"))) / q

    q = max(lot, int(ml / max(loss_per_share(100), 0.01)))
    while q > lot and q * loss_per_share(q) > ml:  # charges have minimums: walk down until it fits
        q -= max(lot, q // 50)
    limits = {"max loss": q}
    limits["max position"] = int(desk.setting(cfg, "max_position_pct") * cap / entry)
    if cash is not None:
        spend = cash - (0 if account else desk.setting(cfg, "cash_reserve_pct") * cap)
        limits["cash"] = int(max(spend, 0) / (entry * 1.004))
    binding = min(limits, key=limits.get)
    qty = limits[binding] // lot * lot
    calc = A.price_calc(b, qty, entry, stop, target, buying=True) if qty > 0 else None
    gap = desk.setting(cfg, "stop_limit_gap")
    sl_limit = math.floor(stop * (1 - gap) * 100 + 1e-9) / 100
    orders = []
    if qty > 0:
        orders = [
            {"id": "E1", "role": "entry", "symbol": plan["symbol"], "side": "BUY", "type": "limit", "qty": qty,
             "limit": round(entry, 2), "style": plan["style"]},
            {"id": "E1-SL", "parent": "E1", "role": "stop", "symbol": plan["symbol"], "side": "SELL", "type": "stop-loss",
             "qty": qty, "trigger": round(stop, 2), "limit": round(sl_limit, 2)},
            {"id": "E1-TP", "parent": "E1", "role": "target", "symbol": plan["symbol"], "side": "SELL", "type": "limit",
             "qty": qty, "limit": round(target, 2), "optional": True},
        ]
        for o in orders:
            o["fingerprint"] = desk.fingerprint(o)
    return {"plan": {k: plan.get(k) for k in ("symbol", "style", "setup", "entry", "stop", "target", "flat_by")},
            "capital": round(cap, 2), "cash": cash, "max_loss": round(ml, 2), "broker": broker, "qty": qty,
            "limited_by": binding, "limits": limits, "calc": calc, "orders": orders}


def show(r):
    p = r["plan"]
    lines = ["BUDGET %s: capital %s, max loss per trade %s (%s)" % (
        p["symbol"], C.fmt_pkr(r["capital"]), C.fmt_pkr(r["max_loss"]), "broker " + (r["broker"] or "PSX minimum charges"))]
    if not r["qty"]:
        lines.append("  0 shares fit your limits (%s). Smaller risk per share, or more capital." % r["limited_by"])
        return "\n".join(lines)
    c = r["calc"]
    lines.append("  buy %d shares at %.2f = %s + %s charges (sized by %s)" % (
        r["qty"], p["entry"], C.fmt_pkr(c["value"]), C.fmt_pkr(c["buy_fees"]), r["limited_by"]))
    lines.append("  at the stop %.2f you lose about %s after charges; at the target %.2f you make about %s" % (
        p["stop"], C.fmt_pkr(c["loss_at_stop"]), p["target"], C.fmt_pkr(c["gain_at_target"])))
    lines.append("  reward-to-risk after charges %.2f to 1; break-even after charges %.2f" % (
        c["reward_risk"] or 0, c["breakeven_price"]))
    lines.append("  BRACKET")
    for o in r["orders"]:
        lines.append("   %-5s %-4s %-10s %6d  %s%s" % (o["id"], o["side"], o["type"], o["qty"],
                                                    "trigger %.2f, limit %.2f" % (o["trigger"], o["limit"]) if o.get("trigger")
                                                    else "limit %.2f" % o["limit"], "  (optional)" if o.get("optional") else ""))
    if p.get("flat_by"):
        lines.append("  and out by %s, whatever happens (a day trade)" % p["flat_by"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--account", type=float, help="size against this capital instead of your portfolio")
    ap.add_argument("--max-loss", type=float, help="rupees you accept losing on this trade")
    ap.add_argument("--write", action="store_true", help="write trader/orders.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    plan = desk.read(h, "plan.json")
    if not plan:
        sys.exit("no plan on file: exitplan.py plan SYMBOL --write")
    try:
        r = size(h, cfg, plan, a.account, a.max_loss)
    except ValueError as e:
        sys.exit(str(e))
    if a.write:
        desk.write(h, "orders.json", dict(r, made=desk.now().isoformat(timespec="minutes")))
        desk.write(h, "risk.json", {"verdicts": []})  # new orders: old verdicts no longer apply
    print(json.dumps(r, indent=1, default=str) if a.json else show(r))
    if not a.json:
        print("Written to trader/orders.json. Next: psx-risk checks it." if a.write else "Add --write to save the bracket.")
        print(desk.DISCLAIMER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
