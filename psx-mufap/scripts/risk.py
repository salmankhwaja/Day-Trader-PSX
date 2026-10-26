#!/usr/bin/env python3
"""Risk calculator: how much risk you can and want to take, and how much you are taking now.

  risk.py quiz                          8 questions -> your risk profile (asks before saving)
  risk.py quiz --answers 3,2,4,3,2,3,3,2 [--save]      the same, without prompts
  risk.py profile [NAME]                compare the four profiles, or switch to one
  risk.py settings                      every buy/sell variable, its value, and where it came from
  risk.py set KEY VALUE                 override one variable (e.g. risk.py set max_holdings 6)
  risk.py unset KEY                     back to your profile's value
  risk.py position --entry 300 --stop 280 [--capital 1000000] [--risk-pct 1] [--target 340]
                                        how many shares, what you could lose and gain
  risk.py portfolio                     your portfolio's risk today: money at risk to the stops,
                                        volatility, value-at-risk, beta, concentration,
                                        allocation vs your target

The quiz scores two things separately, the way financial planners do:
  capacity    how much risk your situation can absorb (time horizon, income, emergency savings,
              share of your savings this is)
  willingness how much risk you are comfortable with (experience, reaction to a fall, goal,
              the worst year you could live with)
Your profile is the LOWER of the two: if you can't afford a loss, liking risk doesn't change
that; if you can afford it but would lose sleep, that matters too.

Choosing a profile changes every variable in profiles.py: what gets ranked highest, how strict
the backtest gates are, stop distances, position sizes, the holdings cap, the cash reserve and
the total amount allowed at risk. Your own overrides (risk.py set) stay on top.
"""
import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import profiles as PR  # noqa: E402

QUESTIONS = [
    # (dimension, question, four answers from lowest to highest risk)
    ("capacity", "When will you need most of this money?",
     ["Within 2 years", "In 2 to 5 years", "In 5 to 10 years", "Not for 10 years or more"]),
    ("capacity", "How steady is your income?",
     ["Uncertain or none", "Somewhat steady", "Steady", "Very secure, with other income too"]),
    ("capacity", "How many months of expenses do you have saved outside this money?",
     ["Less than 1 month", "1 to 3 months", "3 to 6 months", "More than 6 months"]),
    ("capacity", "What share of your total savings is this?",
     ["Over 75%", "50% to 75%", "25% to 50%", "Under 25%"]),
    ("willingness", "How much have you invested in shares before?",
     ["Never", "A little, through funds", "Some shares, for a year or two", "Many years, including a crash"]),
    ("willingness", "Your shares fall 20% in a month. You would…",
     ["Sell everything", "Sell some", "Wait it out", "Buy more"]),
    ("willingness", "What matters most to you?",
     ["Not losing money", "Steady income", "Growth, with some ups and downs", "Maximum growth, big swings are fine"]),
    ("willingness", "The worst year you could live with, for the whole portfolio:",
     ["A 5% loss", "A 10% loss", "A 20% loss", "A 35% loss or more"]),
]
WORST_YEAR = [0.05, 0.10, 0.20, 0.35]


def score_quiz(answers):
    """answers: eight numbers 1..4. Returns the result dict."""
    if len(answers) != len(QUESTIONS) or any(a not in (1, 2, 3, 4) for a in answers):
        raise ValueError("give %d answers, each 1 to 4" % len(QUESTIONS))
    cap = [a for a, q in zip(answers, QUESTIONS) if q[0] == "capacity"]
    wil = [a for a, q in zip(answers, QUESTIONS) if q[0] == "willingness"]
    level = lambda xs: min(4, max(1, int(round(sum(xs) / float(len(xs))))))  # noqa: E731
    lc, lw = level(cap), level(wil)
    # A firm "within 2 years" or "under 1 month saved" caps the profile, whatever the average says.
    if answers[0] == 1 or answers[2] == 1:
        lc = 1
    final = min(lc, lw)
    return {"capacity": lc, "willingness": lw, "profile": PR.ORDER[final - 1],
            "max_annual_loss_pct": WORST_YEAR[answers[7] - 1], "answers": answers,
            "limited_by": "capacity" if lc < lw else ("willingness" if lw < lc else "both")}


KEY_VARS = ["risk_per_trade", "max_position_pct", "max_holdings", "cash_reserve_pct", "max_open_risk_pct",
            "stop_atr_mult", "min_stop_pct", "max_stop_pct", "target_r", "gate_max_drawdown", "gate_min_sharpe",
            "min_avg_volume", "allocation"]


def fmt(v, key=None):
    """Show a setting the way it reads best: fractions as percentages, everything else as is."""
    unit = PR.VARIABLES.get(key, ("", "", ""))[2] if key else ""
    if isinstance(v, dict):
        pct = key in ("allocation", "expected_returns")
        return ", ".join("%s %s" % (k, ("%.0f%%" % (100 * x)) if pct else ("%g" % x)) for k, x in v.items())
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    if isinstance(v, float) and unit.startswith("fraction"):
        return "%.1f%%" % (100 * v) if v else "0%"
    if isinstance(v, float):
        return "%g" % v
    return str(v)


def cmd_quiz(a, h, cfg):
    if a.answers:
        answers = [int(x) for x in a.answers.split(",")]
    else:
        print("Eight questions. Answer 1-4; there are no wrong answers, only expensive ones.\n")
        answers = []
        for i, (_, q, opts) in enumerate(QUESTIONS, 1):
            print("%d. %s" % (i, q))
            for j, o in enumerate(opts, 1):
                print("   %d) %s" % (j, o))
            while True:
                v = input("   your answer: ").strip()
                if v in ("1", "2", "3", "4"):
                    answers.append(int(v))
                    break
                print("   1, 2, 3 or 4 please")
    try:
        res = score_quiz(answers)
    except ValueError as e:
        sys.exit(str(e))
    names = {1: "low", 2: "medium", 3: "high", 4: "very high"}
    print("\nCapacity for risk: %s. Willingness: %s." % (names[res["capacity"]], names[res["willingness"]]))
    print("Your profile: %s%s" % (res["profile"].upper().replace("_", " "),
                                 "" if res["limited_by"] == "both" else
                                 " (set by your %s, the lower of the two)" % res["limited_by"]))
    print("Worst year you'd accept: a %.0f%% loss." % (100 * res["max_annual_loss_pct"]))
    new = PR.PROFILES[res["profile"]]
    print(C.md_table(["Setting", "Now (%s)" % cfg["risk_profile"], "With %s" % res["profile"]],
                     [[k, fmt(cfg.get(k), k), fmt(new.get(k), k)] for k in KEY_VARS]))
    save = a.save
    if not a.answers and not save:
        save = input("\nSave this as your profile? (y/n) ").strip().lower().startswith("y")
    if save:
        C.write_user_config(h, {"risk_profile": res["profile"], "max_annual_loss_pct": res["max_annual_loss_pct"]})
        print("saved: risk_profile = %s. Your own overrides, if any, still apply (risk.py settings)." % res["profile"])
    elif a.answers:
        print("\nNot saved. Add --save to make it your profile.")
    return 0


def cmd_profile(a, h, cfg):
    if a.name:
        if a.name not in PR.PROFILES:
            sys.exit("choose one of: %s" % ", ".join(PR.ORDER))
        C.write_user_config(h, {"risk_profile": a.name})
        user = C.read_user_config(h)
        mine = [k for k in user if k in PR.VARIABLES]
        print("risk profile set to %s%s" % (a.name, "" if not mine else
              ". Your own values still override it for: %s (risk.py unset KEY to drop one)" % ", ".join(mine)))
        return 0
    rows = [[k] + [fmt(PR.PROFILES[p].get(k), k) for p in PR.ORDER] for k in KEY_VARS]
    print(C.md_table(["Setting"] + [p + (" (yours)" if p == cfg["risk_profile"] else "") for p in PR.ORDER], rows))
    print("\nHigher-risk profiles aim for more profit with bigger positions, wider stops and more momentum;"
          " they also lose more when wrong. Switch with: risk.py profile NAME, or take the quiz.")
    return 0


def cmd_settings(a, h, cfg):
    cfg, src = C.load_config(h, with_sources=True)
    print("Risk profile: %s\n" % cfg["risk_profile"])
    groups = {}
    for k, (g, desc, unit) in PR.VARIABLES.items():
        groups.setdefault(g, []).append([k, fmt(cfg.get(k), k), {"profile": "profile", "yours": "YOURS",
                                                                "default": "default"}.get(src.get(k), "default"), desc])
    names = {"screen": "Screening and ranking", "backtest": "Backtest gates for buy ideas", "stops": "Stops and targets",
             "sizing": "Position sizing and limits", "review": "Reviewing holdings", "funds": "Mutual funds",
             "plan": "Allocation, loss tolerance, SIP"}
    for g in ["screen", "backtest", "stops", "sizing", "review", "funds", "plan"]:
        print("%s" % names[g])
        print(C.md_table(["Setting", "Value", "From", "What it does"], groups.get(g, [])))
        print()
    print("Change one: risk.py set KEY VALUE   |   back to the profile: risk.py unset KEY")
    return 0


def parse_value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def cmd_set(a, h, cfg):
    if a.key not in PR.VARIABLES and a.key not in C.DEFAULT_CONFIG:
        sys.exit("unknown setting %r; see risk.py settings" % a.key)
    v = parse_value(a.value)
    if a.key in PR.VARIABLES and isinstance(PR.PROFILES["moderate"][a.key], (int, float)) and \
            not isinstance(v, (int, float)):
        sys.exit("%s needs a number" % a.key)
    C.write_user_config(h, {a.key: v})
    print("%s = %s (yours; overrides the %s profile)" % (a.key, fmt(v, a.key), cfg["risk_profile"]))
    return 0


def cmd_unset(a, h, cfg):
    C.write_user_config(h, {}, remove=[a.key])
    print("%s back to the profile value: %s" % (a.key, fmt(C.load_config(h).get(a.key), a.key)))
    return 0


def position_size(capital, entry, stop, risk_pct, max_position_pct=None, lot=1):
    if stop >= entry:
        raise ValueError("the stop must be below the entry price")
    per_share = entry - stop
    qty = int(capital * risk_pct / per_share)
    cap = int(capital * max_position_pct / entry) if max_position_pct else None
    limited = "risk"
    if cap is not None and cap < qty:
        qty, limited = cap, "max position"
    qty = qty // lot * lot
    return {"qty": qty, "per_share_risk": round(per_share, 2), "risk_pkr": round(qty * per_share, 2),
            "risk_pct_of_capital": qty * per_share / capital if capital else None,
            "position_value": round(qty * entry, 2), "position_pct": qty * entry / capital if capital else None,
            "stop_pct": stop / entry - 1, "limited_by": limited}


def cmd_position(a, h, cfg):
    capital = a.capital
    if capital is None:
        import portfolio as PF
        s = PF.summary(h, PF.load(h))
        capital = s["value"] + (s["cash"] or 0)
        if not capital:
            sys.exit("give --capital (no portfolio or cash recorded yet)")
    risk_pct = (a.risk_pct / 100.0) if a.risk_pct is not None else float(cfg["risk_per_trade"])
    try:
        r = position_size(capital, a.entry, a.stop, risk_pct, float(cfg["max_position_pct"]), int(cfg.get("lot_size") or 1))
    except ValueError as e:
        sys.exit(str(e))
    print("Capital %s, risking %.2f%% (%s) between entry %.2f and stop %.2f (%s):" % (
        C.fmt_pkr(capital), 100 * risk_pct, C.fmt_pkr(capital * risk_pct), a.entry, a.stop, C.fmt_pct(r["stop_pct"])))
    print("  buy %d shares = %s (%.1f%% of capital)%s" % (
        r["qty"], C.fmt_pkr(r["position_value"]), 100 * (r["position_pct"] or 0),
        ", capped by max_position_pct" if r["limited_by"] == "max position" else ""))
    print("  if the stop is hit you lose about %s (%.2f%% of capital) plus charges" % (
        C.fmt_pkr(r["risk_pkr"]), 100 * (r["risk_pct_of_capital"] or 0)))
    target = a.target or a.entry + float(cfg["target_r"]) * (a.entry - a.stop)
    reward = r["qty"] * (target - a.entry)
    print("  at the target %.2f you gain about %s: reward-to-risk %.1f to 1" % (
        target, C.fmt_pkr(reward), (target - a.entry) / (a.entry - a.stop)))
    wins = 1 / (1 + (target - a.entry) / (a.entry - a.stop))
    print("  break-even: right %.0f%% of the time (ignoring charges)" % (100 * wins))
    return 0


BUCKET = {"Money Market": "money_market", "Income": "fixed_income", "Aggressive Fixed Income": "fixed_income",
          "Fixed Rate / Return": "fixed_income", "Capital Protected - Income": "fixed_income",
          "Equity": "equity", "Dedicated Equity": "equity", "Index Tracker": "equity", "Exchange Traded Fund": "equity",
          "Commodities": "equity"}


def bucket_of(category):
    base = (category or "").replace("Shariah Compliant ", "")
    if base in BUCKET:
        return {BUCKET[base]: 1.0}
    if base in ("Asset Allocation", "Balanced", "Fund of Funds", "Fund of Funds - CPPI", "Capital Protected"):
        return {"equity": 0.5, "fixed_income": 0.5}
    return {"fixed_income": 1.0}


def portfolio_risk(h, cfg):
    """Everything risk-related about the real portfolio, as one dict (also used by the dashboard)."""
    import advice as AD
    import portfolio as PF
    lg = PF.load(h)
    s = PF.summary(h, lg)
    cash = s["cash"] or 0.0
    total = s["value"] + cash
    review = AD.review_holdings(h, cfg, lg, s) if s["holdings"] else []
    rv = {r["symbol"]: r for r in review}
    # Allocation
    alloc = {"equity": 0.0, "fixed_income": 0.0, "money_market": cash}
    for p in s["holdings"]:
        alloc["equity"] += p["value"] or p["cost"]
    for f in s["funds"]:
        for b, w in bucket_of(f.get("category")).items():
            alloc[b] += w * (f["value"] or f["cost"])
    alloc_pct = {k: (v / total if total else 0) for k, v in alloc.items()}
    target = cfg.get("allocation") or {}
    # Holdings risk
    rows, sectors = [], {}
    import rank
    for p in s["holdings"]:
        r = rv.get(p["symbol"], {})
        val = p["value"] or p["cost"]
        at_risk = p["qty"] * (p["price"] - r["stop"]) if p.get("price") and r.get("stop") is not None and p["price"] > r["stop"] else 0.0
        info = rank.stock_info(h, cfg, p["symbol"])
        sec = info.get("sector") or "UNKNOWN"
        sectors[sec] = sectors.get(sec, 0) + val
        rows.append({"symbol": p["symbol"], "value": val, "weight": val / total if total else 0, "stop": r.get("stop"),
                     "to_stop_pct": (r["stop"] / p["price"] - 1) if p.get("price") and r.get("stop") else None,
                     "at_risk": round(at_risk, 2), "sector": sec, "action": r.get("action")})
    open_risk = sum(x["at_risk"] for x in rows)
    # Daily returns of the share portfolio (today's weights over the last year)
    series = {}
    for p in s["holdings"]:
        path = C.price_path(h, p["symbol"])
        if os.path.exists(path):
            series[p["symbol"]] = {r["date"]: r["close"] for r in C.read_prices(path)[-260:]}
    eq_value = sum(x["value"] for x in rows)
    port_rets, bench_rets = [], []
    vol = var1 = var21 = beta = mdd = None
    if series and eq_value:
        dates = sorted(set.intersection(*[set(v) for v in series.values()]))[-251:]
        w = {x["symbol"]: x["value"] / eq_value for x in rows if x["symbol"] in series}
        for i in range(1, len(dates)):
            port_rets.append(sum(w[sy] * (series[sy][dates[i]] / series[sy][dates[i - 1]] - 1) for sy in w))
        bpath = C.price_path(h, cfg["benchmark"])
        if os.path.exists(bpath):
            b = {r["date"]: r["close"] for r in C.read_prices(bpath)}
            pairs = [(port_rets[i - 1], b[dates[i]] / b[dates[i - 1]] - 1) for i in range(1, len(dates))
                     if dates[i] in b and dates[i - 1] in b]
            if len(pairs) > 20:
                pr_, br_ = zip(*pairs)
                vb = statistics.pvariance(br_)
                if vb:
                    mp, mb = statistics.mean(pr_), statistics.mean(br_)
                    beta = sum((x - mp) * (y - mb) for x, y in pairs) / len(pairs) / vb
        if len(port_rets) > 20:
            vol = C.ann_vol(port_rets)
            srt = sorted(port_rets)
            var1 = -srt[int(0.05 * len(srt))] * eq_value
            idx = [1.0]
            for x in port_rets:
                idx.append(idx[-1] * (1 + x))
            mdd = C.max_drawdown(idx)
            month = sorted(idx[i + 21] / idx[i] - 1 for i in range(len(idx) - 21))
            var21 = -month[int(0.05 * len(month))] * eq_value if month else None
    weights = [x["value"] / eq_value for x in rows] if eq_value else []  # concentration among your shares
    hhi = sum(x * x for x in weights)
    budget = float(cfg["max_open_risk_pct"]) * total
    worst = float(cfg.get("max_annual_loss_pct") or 0.2) * total
    flags = []
    if open_risk > budget:
        flags.append("open risk %s is over your budget of %s: tighten stops, trim, or skip new buys" % (
            C.fmt_pkr(open_risk), C.fmt_pkr(budget)))
    if var21 and var21 > worst:
        flags.append("a bad month (5%% chance) could cost %s, more than the %s worst year you accepted" % (
            C.fmt_pkr(var21), C.fmt_pkr(worst)))
    for k, v in target.items():
        if total and abs(alloc_pct.get(k, 0) - v) > 0.10:
            flags.append("%s is %.0f%% of your money vs a %.0f%% target" % (k.replace("_", " "), 100 * alloc_pct.get(k, 0), 100 * v))
    top_sector = max(sectors.items(), key=lambda kv: kv[1]) if sectors else None
    if top_sector and total and top_sector[1] / total > 0.4:
        flags.append("%.0f%% of your money is in one sector (%s)" % (100 * top_sector[1] / total, top_sector[0]))
    return {"profile": cfg["risk_profile"], "total": round(total, 2), "cash": round(cash, 2), "equity_value": round(eq_value, 2),
            "holdings": rows, "open_risk": round(open_risk, 2), "open_risk_pct": open_risk / total if total else None,
            "risk_budget": round(budget, 2), "max_annual_loss_pct": cfg.get("max_annual_loss_pct"),
            "volatility": vol, "var_1d_95": var1, "var_1m_95": var21, "beta": beta, "max_drawdown_1y": mdd,
            "effective_holdings": (1 / hhi) if hhi else None, "sectors": {k: round(v, 2) for k, v in sectors.items()},
            "allocation": {k: round(v, 2) for k, v in alloc.items()}, "allocation_pct": alloc_pct,
            "allocation_target": target, "flags": flags, "days": len(port_rets)}


def cmd_portfolio(a, h, cfg):
    r = portfolio_risk(h, cfg)
    if a.json:
        print(json.dumps(r, indent=1, default=str))
        return 0
    if not r["total"]:
        sys.exit("nothing recorded yet: portfolio.py buy ..., fund-buy ..., or cash deposit ...")
    print("Portfolio risk, profile %s. Total %s (cash %s)." % (r["profile"], C.fmt_pkr(r["total"]), C.fmt_pkr(r["cash"])))
    if r["holdings"]:
        print(C.md_table(["Stock", "Weight", "Stop", "To stop", "At risk", "Sector", "Action"],
                         [[x["symbol"], "%.1f%%" % (100 * x["weight"]), "n/a" if x["stop"] is None else "%.2f" % x["stop"],
                           ("under stop" if (x["to_stop_pct"] or 0) > 0 else C.fmt_pct(x["to_stop_pct"])), C.fmt_pkr(x["at_risk"]), (x["sector"] or "")[:22], x["action"] or ""]
                          for x in sorted(r["holdings"], key=lambda x: -x["weight"])]))
    print("\nIf every stop were hit today: %s (%.1f%% of the portfolio); budget %s (max_open_risk_pct %s)." % (
        C.fmt_pkr(r["open_risk"]), 100 * (r["open_risk_pct"] or 0), C.fmt_pkr(r["risk_budget"]),
        fmt(cfg["max_open_risk_pct"], "max_open_risk_pct")))
    if r["volatility"] is not None:
        print("Shares, last %d days: volatility %s a year, beta to KSE-100 %s, worst fall %s." % (
            r["days"], C.fmt_pct(r["volatility"]), "n/a" if r["beta"] is None else "%.2f" % r["beta"], C.fmt_pct(r["max_drawdown_1y"])))
        print("Value-at-risk (95%%): a bad day costs about %s; a bad month about %s." % (
            C.fmt_pkr(r["var_1d_95"]), C.fmt_pkr(r["var_1m_95"])))
    if r["effective_holdings"]:
        print("Diversification: your %d shares behave like %.1f equal-sized positions." % (
            len(r["holdings"]), r["effective_holdings"]))
    print("\nAllocation vs your target:")
    print(C.md_table(["Bucket", "Now", "Target"], [[k.replace("_", " "), "%.0f%%" % (100 * r["allocation_pct"].get(k, 0)),
                                                    "%.0f%%" % (100 * r["allocation_target"].get(k, 0))]
                                                   for k in ("equity", "fixed_income", "money_market")]))
    if r["flags"]:
        print("\nWorth attention:")
        for f in r["flags"]:
            print("  - " + f)
    else:
        print("\nNothing flagged: risk is within your profile's limits.")
    print("\nValue-at-risk uses the last year's daily moves at today's weights; tomorrow is under no obligation "
          "to behave like last year.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("quiz")
    p.add_argument("--answers", help="eight answers 1-4, comma-separated")
    p.add_argument("--save", action="store_true")
    p = sub.add_parser("profile")
    p.add_argument("name", nargs="?", choices=PR.ORDER)
    sub.add_parser("settings")
    p = sub.add_parser("set")
    p.add_argument("key")
    p.add_argument("value")
    p = sub.add_parser("unset")
    p.add_argument("key")
    p = sub.add_parser("position")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--capital", type=float)
    p.add_argument("--risk-pct", type=float, help="percent of capital to risk (default: profile's risk_per_trade)")
    p.add_argument("--target", type=float)
    p = sub.add_parser("portfolio")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"quiz": cmd_quiz, "profile": cmd_profile, "settings": cmd_settings, "set": cmd_set, "unset": cmd_unset,
            "position": cmd_position, "portfolio": cmd_portfolio}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
