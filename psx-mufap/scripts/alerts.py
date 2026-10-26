#!/usr/bin/env python3
"""psx-alerts: rings when a price, a stop, a target or the clock hits. Each alert rings once.

  alerts.py add OGDC --above 310               price at or above
  alerts.py add OGDC --below 290 --note "support"
  alerts.py add OGDC --move 4                  up or down 4% from yesterday's close
  alerts.py add --at 15:20 --note "flat by the close"     a clock alert, Pakistan time
  alerts.py add --from-plan                    the plan's stop, target and flat-by time
  alerts.py add --from-holdings                every holding's stop (from your portfolio)
  alerts.py add --bells                        the opening bell and 10 minutes before the close
  alerts.py list | remove ID | clear [--fired]
  alerts.py check                              one live-price request; rings what hit
  alerts.py watch --every 60                   keep checking while the market is open

Prices come from the PSX portal's market watch: one request covers every share, so watching
thirty alerts costs the same as watching one. A ring prints to the screen with a bell, and also
goes to your phone's notifications in Termux (termux-notification) or your desktop (notify-send)
when those are installed; --notify-cmd 'your command {title} {text}' sends it anywhere else.
On a schedule, `alerts.py check` from cron every few minutes during market hours does the same.

Alerts live in <home>/trader/alerts.json.
"""
import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402


def load(h):
    return desk.read(h, "alerts.json", {"rules": [], "next_id": 1}) or {"rules": [], "next_id": 1}


def save(h, doc):
    desk.write(h, "alerts.json", doc)


def add_rule(doc, **r):
    r = {k: v for k, v in r.items() if v is not None}
    for x in doc["rules"]:  # the same alert twice is one alert
        if all(x.get(k) == r.get(k) for k in ("symbol", "kind", "level", "time")) and not x.get("fired_at"):
            return x
    r["id"] = doc["next_id"]
    doc["next_id"] += 1
    doc["rules"].append(r)
    return r


def describe(r):
    if r["kind"] == "time":
        return "%s at %s" % (r.get("note") or "clock", r["time"])
    what = {"above": "at or above %.2f", "below": "at or below %.2f", "move": "moves %.1f%% from yesterday's close",
            "stop": "hits its stop %.2f", "target": "reaches its target %.2f"}[r["kind"]] % r["level"]
    return "%s %s%s" % (r["symbol"], what, " (%s)" % r["note"] if r.get("note") else "")


def hit(r, q):
    p = q.get("current")
    if p is None:
        return False
    if r["kind"] in ("above", "target"):
        return p >= r["level"]
    if r["kind"] in ("below", "stop"):
        return p <= r["level"]
    if r["kind"] == "move" and q.get("ldcp"):
        return abs(p / q["ldcp"] - 1) * 100 >= r["level"]
    return False


def notify(title, text, cmd=None):
    print("\a*** %s: %s" % (title, text), flush=True)
    try:
        if cmd:
            subprocess.run([x.format(title=title, text=text) for x in shlex.split(cmd)], timeout=15)
        elif shutil.which("termux-notification"):
            subprocess.run(["termux-notification", "--title", title, "--content", text, "--sound"], timeout=15)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, text], timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def check(h, cfg, now=None, quotes=None, notify_cmd=None, quiet=False):
    """Ring every alert that hit, once. Returns the rules that rang."""
    import freshness as F
    now = now or C.pk_now()
    doc = load(h)
    live = [r for r in doc["rules"] if not r.get("fired_at")]
    if not live:
        return []
    if quotes is None and any(r["kind"] != "time" for r in live):
        try:
            quotes = F.fetch_live(h)["quotes"]
        except Exception as e:  # noqa: BLE001
            if not quiet:
                print("Live prices failed (%s); only clock alerts checked." % e)
            quotes = {}
    rang = []
    for r in live:
        if r["kind"] == "time":
            ok = now.strftime("%H:%M") >= r["time"] and (r.get("date") in (None, now.date().isoformat()))
        else:
            q = (quotes or {}).get(r["symbol"])
            ok = bool(q) and hit(r, q)
            if ok:
                r["price"] = q["current"]
        if ok:
            r["fired_at"] = now.isoformat(timespec="minutes")
            rang.append(r)
            notify("PSX alert", describe(r) + (" - now %.2f" % r["price"] if r.get("price") is not None else ""), notify_cmd)
    save(h, doc)
    return rang


def cmd_add(a, h, cfg):
    doc = load(h)
    added = []
    today = desk.now(a.now).date().isoformat()
    sym = a.symbol.upper() if a.symbol else None
    if a.above is not None:
        added.append(add_rule(doc, symbol=sym, kind="above", level=a.above, note=a.note))
    if a.below is not None:
        added.append(add_rule(doc, symbol=sym, kind="below", level=a.below, note=a.note))
    if a.move is not None:
        added.append(add_rule(doc, symbol=sym, kind="move", level=a.move, note=a.note))
    if a.at:
        added.append(add_rule(doc, kind="time", time=a.at, date=today if not a.daily else None, note=a.note))
    if a.from_plan:
        p = desk.read(h, "plan.json")
        if not p:
            sys.exit("no plan on file: exitplan.py plan SYMBOL --write")
        added.append(add_rule(doc, symbol=p["symbol"], kind="stop", level=p["stop"], note="plan stop"))
        added.append(add_rule(doc, symbol=p["symbol"], kind="target", level=p["target"], note="plan target"))
        if p.get("flat_by"):
            added.append(add_rule(doc, kind="time", time=p["flat_by"], date=today, note="flat by: close the %s day trade" % p["symbol"]))
    if a.from_holdings:
        import portfolio as PF
        import advice as A
        lg = PF.load(h)
        for r in A.review_holdings(h, cfg, lg, PF.summary(h, lg)):
            if r.get("stop"):
                added.append(add_rule(doc, symbol=r["symbol"], kind="stop", level=r["stop"], note="holding stop"))
    if a.bells:
        d = desk.now(a.now).date()
        ss = C.sessions(d)
        if ss:
            added.append(add_rule(doc, kind="time", time=ss[0][0].strftime("%H:%M"), date=today, note="the market is open"))
            added.append(add_rule(doc, kind="time", time=(ss[-1][1] - dt.timedelta(minutes=10)).strftime("%H:%M"),
                                  date=today, note="10 minutes to the close"))
    if not added:
        sys.exit("say what to watch: --above, --below, --move, --at, --from-plan, --from-holdings or --bells")
    if any(r.get("symbol") is None and r["kind"] != "time" for r in added):
        sys.exit("price alerts need a symbol")
    save(h, doc)
    for r in added:
        print("#%d %s" % (r["id"], describe(r)))
    return 0


def cmd_list(a, h, cfg):
    doc = load(h)
    if not doc["rules"]:
        print("No alerts. alerts.py add OGDC --above 310")
        return 0
    print(C.md_table(["#", "Alert", "Rang"], [[r["id"], describe(r), r.get("fired_at") or ""] for r in doc["rules"]]))
    return 0


def cmd_remove(a, h, cfg):
    doc = load(h)
    n = len(doc["rules"])
    doc["rules"] = [r for r in doc["rules"] if r["id"] not in a.ids]
    save(h, doc)
    print("removed %d" % (n - len(doc["rules"])))
    return 0


def cmd_clear(a, h, cfg):
    doc = load(h)
    doc["rules"] = [r for r in doc["rules"] if a.fired and not r.get("fired_at")]
    save(h, doc)
    print("cleared %s" % ("the alerts that rang" if a.fired else "every alert"))
    return 0


def cmd_check(a, h, cfg):
    quotes = None
    if a.from_file:
        import freshness as F
        with open(a.from_file, encoding="utf-8", errors="replace") as f:
            quotes = F.parse_market_watch(f.read())
    rang = check(h, cfg, desk.now(a.now), quotes, a.notify_cmd)
    if not rang:
        print("Nothing hit (market %s)." % C.market_state(desk.now(a.now)))
    return 0


def cmd_watch(a, h, cfg):
    print("Watching alerts every %d s while the market is open (Ctrl+C to stop)." % a.every)
    try:
        while True:
            now = C.pk_now()
            state = C.market_state(now)
            check(h, cfg, now, None if state in ("open", "pre-open") else {}, a.notify_cmd, quiet=True)
            pending = [r for r in load(h)["rules"] if not r.get("fired_at")]
            if not pending:
                print("Every alert has rung.")
                return 0
            if state in ("closed", "weekend") and now > (C.close_time(now.date()) or now):
                print("The market has closed; %d alert(s) left for tomorrow." % len(pending))
                return 0
            time.sleep(a.every)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("symbol", nargs="?")
    p.add_argument("--above", type=float)
    p.add_argument("--below", type=float)
    p.add_argument("--move", type=float, help="percent from yesterday's close")
    p.add_argument("--at", help="HH:MM Pakistan time")
    p.add_argument("--daily", action="store_true", help="a clock alert for every day, not just today")
    p.add_argument("--note")
    p.add_argument("--from-plan", action="store_true")
    p.add_argument("--from-holdings", action="store_true")
    p.add_argument("--bells", action="store_true")
    p.add_argument("--now")
    sub.add_parser("list")
    p = sub.add_parser("remove")
    p.add_argument("ids", nargs="+", type=int)
    p = sub.add_parser("clear")
    p.add_argument("--fired", action="store_true", help="only the ones that rang")
    for n in ("check", "watch"):
        p = sub.add_parser(n)
        p.add_argument("--notify-cmd")
        if n == "check":
            p.add_argument("--from-file", help="a market-watch page you saved")
            p.add_argument("--now")
        else:
            p.add_argument("--every", type=int, default=60)
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"add": cmd_add, "list": cmd_list, "remove": cmd_remove, "clear": cmd_clear, "check": cmd_check,
            "watch": cmd_watch}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
