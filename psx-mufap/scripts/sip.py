#!/usr/bin/env python3
"""SIP calculator: what a monthly investment could grow to, or what you need to invest for a goal.

  sip.py plan --monthly 25000 --years 10                  uses your risk profile's mix (default)
  sip.py plan --monthly 25000 --years 10 --rate 14        your own yearly return, %
  sip.py plan --monthly 25000 --years 10 --fund "Alfalah Cash Fund - II"
  sip.py plan --monthly 25000 --years 10 --symbol OGDC
  sip.py plan --monthly 25000 --years 10 --portfolio      start from what you own today, at its mix
  sip.py goal --target 5000000 --years 8                   the monthly amount that gets you there
  Options for both: --step-up 10 (raise the SIP 10% each year), --lump 100000 (a starting sum),
                    --inflation 10 (also show the result in today's rupees), --json

Where the yearly return comes from (the first that applies):
  --rate                 your number
  --fund NAME            that fund's MUFAP return: 3-year where available, else 1-year, as a yearly rate
  --symbol SYM           that share's own yearly growth over the price history on file (up to 5 years;
                         excludes dividends)
  your risk profile      "allocation" (equity / fixed income / money market) times each part's
                         return, taken from your data when it's on file: KSE-100 growth for equity,
                         the median 1-year MUFAP return of Income and Money Market funds; otherwise
                         the "expected_returns" assumptions in config.json
Every plan also shows the result 3 points lower and 3 points higher, because the future rarely
reads the plan.

Money is invested at the start of each month and compounds monthly. Taxes, loads and charges
are not deducted. Projections, not promises.
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def project(monthly, years, rate, step_up=0.0, lump=0.0):
    """Year-by-year rows: year, monthly SIP that year, invested so far, value at year end."""
    rm = (1 + rate) ** (1 / 12.0) - 1
    value, invested, rows, m = float(lump), float(lump), [], float(monthly)
    for y in range(1, int(years) + 1):
        for _ in range(12):
            value = (value + m) * (1 + rm)
            invested += m
        rows.append({"year": y, "monthly": round(m, 2), "invested": round(invested, 2), "value": round(value, 2),
                     "gain": round(value - invested, 2)})
        m *= 1 + step_up
    return rows


def required_monthly(target, years, rate, step_up=0.0, lump=0.0):
    """Smallest starting monthly SIP whose projection reaches `target` (bisection)."""
    lo, hi = 0.0, max(float(target), 1.0)
    if project(0, years, rate, step_up, lump)[-1]["value"] >= target:
        return 0.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if project(mid, years, rate, step_up, lump)[-1]["value"] >= target:
            hi = mid
        else:
            lo = mid
    return round(hi, 0)


def cagr_of_series(rows, max_years=5):
    rows = rows[-int(max_years * C.TRADING_DAYS + 1):]
    if len(rows) < 120:
        return None
    years = (len(rows) - 1) / float(C.TRADING_DAYS)
    return (rows[-1]["close"] / rows[0]["close"]) ** (1 / years) - 1


def fund_rate(h, name):
    import portfolio as PF
    import rank
    fname = PF.find_fund_name(h, name)
    if not fname:
        raise ValueError("no MUFAP fund matches %r (run pkdata.py mufap)" % name)
    _, rows = rank.fund_rows(h)
    f = next(r for r in rows if r["fund"] == fname)
    if f["return_type"] == "annualized":
        r = f["y3"] if f["y3"] is not None else f["d365"]
        basis = "3-year annualised" if f["y3"] is not None else "1-year annualised"
        rate = None if r is None else r / 100.0
    else:
        if f["y3"] is not None:
            rate, basis = (1 + f["y3"] / 100.0) ** (1 / 3.0) - 1, "3-year return as a yearly rate"
        else:
            rate, basis = (None if f["d365"] is None else f["d365"] / 100.0), "1-year return"
    if rate is None:
        raise ValueError("%s has no 1-year or 3-year return yet" % fname)
    return rate, "%s: %s from MUFAP" % (fname, basis)


def market_rates(h, cfg):
    """Yearly return per allocation bucket, from data on file where possible."""
    rates, src = dict(cfg.get("expected_returns") or {}), {}
    for k in rates:
        src[k] = "assumption in config"
    bp = C.price_path(h, cfg["benchmark"])
    if os.path.exists(bp):
        g = cagr_of_series(C.read_prices(bp))
        if g is not None:
            rates["equity"], src["equity"] = g, "%s growth, history on file" % cfg["benchmark"]
    try:
        import rank
        _, rows = rank.fund_rows(h)
        for bucket, cats in (("money_market", ("Money Market", "Shariah Compliant Money Market")),
                             ("fixed_income", ("Income", "Shariah Compliant Income"))):
            vals = [r["d365"] for r in rows if r["category"] in cats and r["d365"] is not None]
            if vals:
                rates[bucket], src[bucket] = statistics.median(vals) / 100.0, "median 1-year MUFAP return"
    except SystemExit:
        pass
    return rates, src


def blended(weights, rates):
    tot = sum(weights.values())
    return sum(w * rates.get(k, 0) for k, w in weights.items()) / tot if tot else 0.0


def resolve_rate(a, h, cfg):
    """(rate, explanation, lump) from the options."""
    lump = a.lump or 0.0
    if a.rate is not None:
        return a.rate / 100.0, "your rate", lump
    if a.fund:
        r, why = fund_rate(h, a.fund)
        return r, why, lump
    if a.symbol:
        p = C.price_path(h, a.symbol.upper())
        if not os.path.exists(p):
            raise ValueError("no prices for %s (pkdata.py psx %s)" % (a.symbol.upper(), a.symbol.upper()))
        g = cagr_of_series(C.read_prices(p))
        if g is None:
            raise ValueError("not enough price history for %s" % a.symbol.upper())
        return g, "%s yearly growth over its history on file (dividends excluded)" % a.symbol.upper(), lump
    rates, src = market_rates(h, cfg)
    if getattr(a, "portfolio", False):
        import risk
        pr = risk.portfolio_risk(h, cfg)
        if not pr["total"]:
            raise ValueError("nothing recorded in your portfolio yet")
        r = blended(pr["allocation"], rates)
        why = "your portfolio's current mix (%s) at %s" % (
            ", ".join("%s %.0f%%" % (k.replace("_", " "), 100 * v) for k, v in pr["allocation_pct"].items()),
            ", ".join("%s %s (%s)" % (k.replace("_", " "), C.fmt_pct(rates[k]), src[k]) for k in rates))
        return r, why, lump + pr["total"]
    alloc = cfg.get("allocation") or {"equity": 0.5, "fixed_income": 0.3, "money_market": 0.2}
    r = blended(alloc, rates)
    why = "%s profile mix (%s) at %s" % (
        cfg["risk_profile"], ", ".join("%s %.0f%%" % (k.replace("_", " "), 100 * v) for k, v in alloc.items()),
        ", ".join("%s %s (%s)" % (k.replace("_", " "), C.fmt_pct(rates[k]), src[k]) for k in alloc))
    return r, why, lump


def real(value, years, inflation):
    return value / ((1 + inflation) ** years) if inflation else None


def cmd_plan(a, h, cfg):
    try:
        rate, why, lump = resolve_rate(a, h, cfg)
    except ValueError as e:
        sys.exit(str(e))
    step, infl = (a.step_up or 0) / 100.0, (a.inflation or 0) / 100.0
    rows = project(a.monthly, a.years, rate, step, lump)
    scen = {"lower": project(a.monthly, a.years, rate - 0.03, step, lump)[-1]["value"],
            "base": rows[-1]["value"], "higher": project(a.monthly, a.years, rate + 0.03, step, lump)[-1]["value"]}
    if a.json:
        print(json.dumps({"rate": rate, "basis": why, "lump": lump, "rows": rows, "scenarios": scen,
                          "real_value": real(rows[-1]["value"], a.years, infl)}, indent=1))
        return 0
    print("SIP of %s a month for %d years%s%s, at %s a year." % (
        C.fmt_pkr(a.monthly), a.years, ", rising %.0f%% a year" % (100 * step) if step else "",
        ", starting with %s" % C.fmt_pkr(lump) if lump else "", C.fmt_pct(rate)))
    print("Rate basis: %s.\n" % why)
    show = rows if len(rows) <= 12 else [r for r in rows if r["year"] in (1, 2, 3, 5) or r["year"] % 5 == 0 or r["year"] == len(rows)]
    print(C.md_table(["Year", "Monthly", "Invested", "Value", "Gain"],
                     [[r["year"], C.fmt_pkr(r["monthly"]), C.fmt_pkr(r["invested"]), C.fmt_pkr(r["value"]), C.fmt_pkr(r["gain"])]
                      for r in show]))
    last = rows[-1]
    print("\nAfter %d years: %s invested grows to about %s." % (a.years, C.fmt_pkr(last["invested"]), C.fmt_pkr(last["value"])))
    if infl:
        print("In today's rupees (inflation %.0f%%): about %s." % (100 * infl, C.fmt_pkr(real(last["value"], a.years, infl))))
    print("If returns are 3 points lower: %s; 3 points higher: %s." % (C.fmt_pkr(scen["lower"]), C.fmt_pkr(scen["higher"])))
    print("Before taxes, loads and charges. A projection, not a promise.")
    return 0


def cmd_goal(a, h, cfg):
    try:
        rate, why, lump = resolve_rate(a, h, cfg)
    except ValueError as e:
        sys.exit(str(e))
    step, infl = (a.step_up or 0) / 100.0, (a.inflation or 0) / 100.0
    target = a.target * ((1 + infl) ** a.years) if (infl and a.today_rupees) else a.target
    need = required_monthly(target, a.years, rate, step, lump)
    lower = required_monthly(target, a.years, rate - 0.03, step, lump)
    if a.json:
        print(json.dumps({"rate": rate, "basis": why, "target": target, "monthly": need, "monthly_if_3pts_lower": lower},
                         indent=1))
        return 0
    print("Goal: %s in %d years%s, at %s a year (%s)." % (
        C.fmt_pkr(target), a.years, " (%s in today's rupees, inflation %.0f%%)" % (C.fmt_pkr(a.target), 100 * infl)
        if (infl and a.today_rupees) else "", C.fmt_pct(rate), why))
    if need == 0:
        print("Your starting sum of %s gets there on its own. Nice." % C.fmt_pkr(lump))
        return 0
    print("Invest about %s a month%s%s." % (C.fmt_pkr(need), ", raising it %.0f%% every year" % (100 * step) if step else "",
                                           ", on top of %s now" % C.fmt_pkr(lump) if lump else ""))
    print("If returns come in 3 points lower, you'd need about %s a month." % C.fmt_pkr(lower))
    return 0


def add_rate_options(p):
    p.add_argument("--years", type=int, required=True)
    p.add_argument("--rate", type=float, help="yearly return, %")
    p.add_argument("--fund", help="use a MUFAP fund's return")
    p.add_argument("--symbol", help="use a share's own historical growth")
    p.add_argument("--step-up", type=float, help="raise the SIP by this % every year")
    p.add_argument("--lump", type=float, help="a starting amount")
    p.add_argument("--inflation", type=float, help="yearly inflation, % (shows today's rupees)")
    p.add_argument("--json", action="store_true")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--monthly", type=float, required=True)
    p.add_argument("--portfolio", action="store_true", help="start from your portfolio today, at its current mix")
    add_rate_options(p)
    p = sub.add_parser("goal")
    p.add_argument("--target", type=float, required=True)
    p.add_argument("--today-rupees", action="store_true", help="the target is in today's money (needs --inflation)")
    add_rate_options(p)
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"plan": cmd_plan, "goal": cmd_goal}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
