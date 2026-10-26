#!/usr/bin/env python3
"""psx-exit: the way out, decided before the way in. Stop, target and (for a day trade) flat-by time.

  exitplan.py plan OGDC                          from today's scanner setup: its trigger and stop idea
  exitplan.py plan OGDC --entry 301.5 --stop or-mid --target 2R --style day --write
  exitplan.py plan OGDC --stop vol --target 2.5R --style swing --days 10 --write
  exitplan.py show                               the plan on file

Stops (--stop):
  or-mid / or-low   the middle / bottom of today's opening range (day trades after an ORB)
  setup             the scanner's stop idea for this share
  vol               entry - stop_atr_mult x the average daily move, kept between min_stop_pct and
                    max_stop_pct below entry (as the portfolio advice does)
  5%                a percentage below entry
  287.50            a price
Targets (--target): "2R" = entry + 2 x the risk per share (default: min_reward_risk for a day
trade, target_r for a swing), or a price.

Flat-by: a day trade is closed flat_by_min minutes before the close (15:30 Monday-Thursday, 16:30
Friday; so 15:20 / 16:20 by default). PSX prices can't move more than the daily price limit (10%,
or Rs 1) from yesterday's close, so a day-trade target beyond the band can't fill today: the plan
says so. Reward-to-risk is checked after estimated charges at your default broker.

Writes <home>/trader/plan.json for psx-timemachine, psx-budget, psx-risk and psx-alerts.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402


def _setup_for(h, symbol):
    s = desk.read(h, "setups.json", {}) or {}
    return next((x for x in s.get("setups", []) if x.get("symbol") == symbol), None), s.get("mode")


def _price_now(h, symbol):
    import freshness as F
    snap = F.load_live(h)
    if snap and snap.get("date") == C.pk_now().date().isoformat() and symbol in snap.get("quotes", {}):
        return snap["quotes"][symbol]["current"], "live %s" % snap["fetched"][11:16]
    d, c = desk.last_close(h, symbol)
    return c, "close of %s" % d if d else None


def vol_stop(h, cfg, symbol, entry):
    import advice as A
    rows = C.read_prices(C.price_path(h, symbol), live=False)
    st = A.stop_for(rows, entry, rows[-1]["date"], cfg)
    return st["initial"]


def make_plan(h, cfg, symbol, entry=None, stop="auto", target=None, style=None, days=10, now=None):
    symbol = symbol.upper()
    now = now or C.pk_now()
    setup, mode = _setup_for(h, symbol)
    style = style or ("day" if mode in ("orb", "movers") else "swing")
    notes = []
    src = None
    if entry is None:
        if setup and setup.get("setup") == "orb" and setup.get("last", 0) > setup["trigger"]:
            entry, src = float(setup["last"]), "last trade %s, already above the range" % setup.get("last_time")
        elif setup:
            entry, src = float(setup["trigger"]), "the %s trigger" % setup.get("setup")
        else:
            entry, src = _price_now(h, symbol)
            if entry is None:
                raise ValueError("no price on file for %s: pkdata.py psx %s (or give --entry)" % (symbol, symbol))
    entry = float(entry)
    s = (stop or "auto").lower()
    if s == "auto":
        s = "or-mid" if (setup and setup.get("setup") == "orb") else ("setup" if setup else "vol")
    if s in ("or-mid", "or-low"):
        if not setup or "or_low" not in setup:
            raise ValueError("no opening range on file for %s: run scanner.py orb first, or pick another stop" % symbol)
        stop_px = setup["or_mid"] if s == "or-mid" else setup["or_low"]
    elif s == "setup":
        if not setup:
            raise ValueError("no scanner setup for %s today" % symbol)
        stop_px = float(setup["stop"])
    elif s == "vol":
        stop_px = vol_stop(h, cfg, symbol, entry)
    elif s.endswith("%"):
        stop_px = entry * (1 - float(s[:-1]) / 100.0)
    else:
        stop_px = float(s)
    stop_px = round(stop_px, 2)
    if stop_px >= entry:
        raise ValueError("the stop (%.2f) must be below the entry (%.2f)" % (stop_px, entry))
    risk = entry - stop_px
    tgt = target or ("%gR" % (desk.setting(cfg, "min_reward_risk") if style == "day" else desk.setting(cfg, "target_r")))
    if str(tgt).upper().endswith("R"):
        tgt_px = entry + float(str(tgt)[:-1]) * risk
    else:
        tgt_px = float(tgt)
    tgt_px = round(tgt_px, 2)
    if tgt_px <= entry:
        raise ValueError("the target (%.2f) must be above the entry (%.2f)" % (tgt_px, entry))
    _, ldcp = desk.last_close(h, symbol)
    band = list(C.circuit_band(ldcp, cfg)) if ldcp else None
    flat_by = None
    if style == "day":
        close = C.close_time(now.date())
        if close is None:
            notes.append("PSX is closed today (weekend): this plan is for the next session")
            nxt = now.date() + dt.timedelta(days=1)
            while not C.sessions(nxt):
                nxt += dt.timedelta(days=1)
            close = C.close_time(nxt)
        flat_by = (close - dt.timedelta(minutes=desk.setting(cfg, "flat_by_min"))).strftime("%H:%M")
        if band and tgt_px > band[1]:
            notes.append("target %.2f is above today's upper price limit %.2f: it can't fill today" % (tgt_px, band[1]))
        if band and stop_px < band[0]:
            notes.append("stop %.2f is below today's lower price limit %.2f: a locked limit-down day can leave you "
                         "unable to sell at all" % (stop_px, band[0]))
    import portfolio as PF
    lg = PF.load(h)
    broker = lg.get("default_broker")
    b = lg["brokers"].get(broker) if broker else None
    per_share_fees = (sum(PF.estimate_charges(b, 100, entry, "buy")) + sum(PF.estimate_charges(b, 100, tgt_px, "sell"))) / 100
    per_share_fees_stop = (sum(PF.estimate_charges(b, 100, entry, "buy")) + sum(PF.estimate_charges(b, 100, stop_px, "sell"))) / 100
    rr_net = (tgt_px - entry - per_share_fees) / (risk + per_share_fees_stop)
    if style == "day" and rr_net < desk.setting(cfg, "min_reward_risk"):
        notes.append("after charges the reward is %.2f times the risk, under your min_reward_risk %.1f: psx-risk will block it"
                     % (rr_net, desk.setting(cfg, "min_reward_risk")))
    return {"symbol": symbol, "style": style, "setup": (setup or {}).get("setup"), "entry": round(entry, 2),
            "entry_from": src or "given", "stop": stop_px, "stop_rule": s, "target": tgt_px, "target_rule": str(tgt),
            "risk_per_share": round(risk, 2), "reward_per_share": round(tgt_px - entry, 2),
            "reward_risk": round((tgt_px - entry) / risk, 2), "reward_risk_after_charges": round(rr_net, 2),
            "flat_by": flat_by, "days": days if style == "swing" else 1, "band": band, "broker": broker,
            "made": now.isoformat(timespec="minutes"), "notes": notes}


def show(p):
    lines = ["PLAN %s (%s trade%s)" % (p["symbol"], p["style"], ", " + p["setup"] + " setup" if p.get("setup") else ""),
             "  entry   %.2f  (%s)" % (p["entry"], p.get("entry_from")),
             "  stop    %.2f  (%s; %.2f a share at risk, %.1f%%)" % (p["stop"], p["stop_rule"], p["risk_per_share"],
                                                                    100 * p["risk_per_share"] / p["entry"]),
             "  target  %.2f  (%s; %.1f to 1, %.1f to 1 after charges)" % (p["target"], p["target_rule"], p["reward_risk"],
                                                                          p["reward_risk_after_charges"])]
    if p.get("flat_by"):
        lines.append("  flat by %s Pakistan time, whatever happens" % p["flat_by"])
    else:
        lines.append("  horizon about %d sessions; review it daily (portfolio.py advise)" % p.get("days", 10))
    if p.get("band"):
        lines.append("  today's price limits %.2f - %.2f" % tuple(p["band"]))
    for n in p.get("notes") or []:
        lines.append("  note: " + n)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("symbol")
    p.add_argument("--entry", type=float)
    p.add_argument("--stop", default="auto")
    p.add_argument("--target")
    p.add_argument("--style", choices=["day", "swing"])
    p.add_argument("--days", type=int, default=10, help="swing: sessions to plan for")
    p.add_argument("--now")
    p.add_argument("--write", action="store_true", help="save as trader/plan.json")
    p.add_argument("--json", action="store_true")
    sub.add_parser("show")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    if a.cmd == "show":
        p = desk.read(h, "plan.json")
        print(show(p) if p else "No plan on file: exitplan.py plan SYMBOL --write")
        return 0
    try:
        plan = make_plan(h, cfg, a.symbol, a.entry, a.stop, a.target, a.style, a.days, desk.now(a.now))
    except ValueError as e:
        sys.exit(str(e))
    if a.write:
        desk.write(h, "plan.json", plan)
    if a.json:
        print(json.dumps(plan, indent=1))
        return 0
    print(show(plan))
    print("Saved to trader/plan.json. Next: psx-timemachine for the odds, psx-budget to size it." if a.write
          else "Add --write to save it for the next steps.")
    print(desk.DISCLAIMER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
