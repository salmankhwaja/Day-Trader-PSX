#!/usr/bin/env python3
"""Which MUFAP mutual funds to hold: suggestions by risk profile, and a check on the funds you own.

  funds.py advise --risk low|medium|high [--shariah] [--top 3]
  funds.py review                         your funds (recorded with portfolio.py fund-buy) vs their category

Risk profiles map to MUFAP categories:
  low     Money Market                        capital stability, daily liquidity
  medium  Income, Aggressive Fixed Income      bonds and longer instruments; small price swings
          Asset Allocation, Balanced, Fund of Funds   mix of equity and fixed income
  high    Equity, Index Tracker, Dedicated Equity     stock market risk and return
With --shariah the Shariah-compliant version of each category is used instead.

Within each category funds are ranked on the average percentile of their 30-day, 90-day and
1-year returns (at least two of the three needed), so a fund needs a consistent record. Funds
whose NAV is more than 5 days old are left out. Returns are after fund expenses but before any
sales load. Money market and income categories quote annualised returns; equity and mixed
categories quote absolute returns: never compare across those groups.

`review` marks a fund you hold REVIEW when it ranks in the bottom third of its category, and
names the category's leaders; otherwise HOLD.

Past returns do not predict future returns. Not investment advice.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import rank  # noqa: E402

PROFILES = {
    "low": ["Money Market"],
    "medium": ["Income", "Aggressive Fixed Income", "Asset Allocation", "Balanced", "Fund of Funds"],
    "high": ["Equity", "Index Tracker", "Dedicated Equity"],
}
WHY = {
    "Money Market": "short-term deposits and T-bills: steady, liquid, low risk",
    "Income": "bonds and longer instruments: a little more return than money market, small price swings",
    "Aggressive Fixed Income": "riskier debt for higher yield",
    "Asset Allocation": "manager moves between shares and fixed income",
    "Balanced": "a fixed mix of shares and fixed income",
    "Fund of Funds": "a basket of the AMC's other funds",
    "Equity": "PSX shares: highest long-run return and the biggest swings",
    "Index Tracker": "follows a PSX index at low cost",
    "Dedicated Equity": "shares, for institutional or pension use",
}


def category_name(base, shariah):
    return ("Shariah Compliant " + base) if shariah else base


def ranked_by_category(h):
    date, rows = rank.fund_rows(h)
    return date, rank.rank_funds(rows)


def fresh(f, report_date, days=5):
    try:
        return (dt.date.fromisoformat(report_date) - dt.date.fromisoformat(f["validity_date"])).days <= days
    except (TypeError, ValueError):
        return True


def advise(h, risk, shariah=False, top=3):
    date, by = ranked_by_category(h)
    stale = int(C.load_config(h).get("fund_stale_days", 5))
    out = []
    for base in PROFILES[risk]:
        cat = category_name(base, shariah)
        fs = [f for f in by.get(cat, []) if f.get("score") is not None and fresh(f, date, stale)]
        if not fs:
            continue
        out.append({"category": cat, "why": WHY.get(base, ""), "return_type": fs[0]["return_type"],
                    "funds": fs[:top], "count": len(by.get(cat, []))})
    return date, out


def review(h):
    import portfolio as PF
    lg = PF.load(h)
    held, _ = PF.fund_holdings(h, lg)
    date, by = ranked_by_category(h)
    bottom = float(C.load_config(h).get("fund_review_bottom", 1 / 3.0))
    out = []
    for f in held:
        cat = f.get("category")
        fs = by.get(cat, []) if cat else []
        ranked = [x for x in fs if x.get("score") is not None]
        pos = next((i for i, x in enumerate(ranked) if x["fund"] == f["fund"]), None)
        r = {"fund": f["fund"], "category": cat, "value": f["value"], "unrealised_pct": f["unrealised_pct"]}
        if pos is None:
            r.update(action="NO DATA", why="not ranked in today's MUFAP table (missing returns or category)")
        else:
            pct_rank = 1 - pos / max(len(ranked) - 1, 1)
            r["rank"] = "%d of %d" % (pos + 1, len(ranked))
            leaders = [x["fund"] for x in ranked[:3] if x["fund"] != f["fund"]][:2]
            if pct_rank < bottom:
                r.update(action="REVIEW", why="in the bottom %.0f%% of %s on 30-day, 90-day and 1-year returns; "
                         "leaders: %s" % (100 * bottom, cat, ", ".join(leaders)))
            else:
                r.update(action="HOLD", why="ranked %s in %s" % (r["rank"], cat))
        out.append(r)
    return date, out


def p1(x):
    return "n/a" if x is None else "%.1f" % x


def cmd_advise(a, h, cfg):
    date, out = advise(h, a.risk, a.shariah, a.top)
    if a.json:
        print(json.dumps({"date": date, "risk": a.risk, "shariah": a.shariah, "categories": out}, indent=1, default=str))
        return 0
    if not out:
        sys.exit("no ranked funds for that profile in the %s MUFAP table" % date)
    print("Funds for a %s-risk profile%s, MUFAP report %s" % (a.risk, " (Shariah-compliant)" if a.shariah else "", date))
    for c in out:
        print("\n%s: %s (%s returns, %%; %d funds in category)" % (c["category"], c["why"], c["return_type"], c["count"]))
        print(C.md_table(["#", "Fund", "Rating", "30D", "90D", "YTD", "1Y", "3Y", "Score"],
                         [[i, f["fund"], f.get("rating") or "", p1(f["d30"]), p1(f["d90"]), p1(f["ytd"]),
                           p1(f["d365"]), p1(f["y3"]), p1(f["score"])] for i, f in enumerate(c["funds"], 1)]))
    print("\nRanked inside each category only. Returns exclude sales loads: check the fund's offering "
          "document for loads and its AMC's fact sheet before investing. Past returns are not a forecast, and "
          "this is not investment advice.")
    return 0


def cmd_review(a, h, cfg):
    date, out = review(h)
    if not out:
        print("no funds recorded: portfolio.py fund-buy \"FUND NAME\" AMOUNT")
        return 0
    print("Your funds vs their MUFAP category, report %s" % date)
    print(C.md_table(["Fund", "Value", "P/L", "Action", "Why"],
                     [[r["fund"], C.fmt_pkr(r["value"]), C.fmt_pct(r["unrealised_pct"]), r["action"], r["why"]]
                      for r in out]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("advise")
    p.add_argument("--risk", choices=list(PROFILES), default="low")
    p.add_argument("--shariah", action="store_true")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--json", action="store_true")
    sub.add_parser("review")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"advise": cmd_advise, "review": cmd_review}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
