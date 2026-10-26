#!/usr/bin/env python3
"""psx-analyst: a company's latest results, and what changed, from its PSX page.

  analyst.py OGDC                      latest quarter and year: sales, profit, EPS, margins, growth
  analyst.py OGDC MARI PPL             side by side
  analyst.py OGDC --cached             what's on file (company pages are kept by pkdata.py company)
  analyst.py OGDC --from-file page.html

Source: the Financials and Ratios sections of https://dps.psx.com.pk/company/<SYMBOL> (annual and
quarterly sales, profit after tax and EPS; margins and EPS growth; figures in thousands of rupees,
EPS in rupees), plus the company's results announcements and payouts. The portal credits Capital
Stake for these figures and says they may be standardised: for "as reported" numbers, open the
results PDF (linked in the output).

What it works out:
  latest quarter vs the same quarter last year (the portal lists it), and vs the quarter before
  latest year vs the year before: sales, profit after tax, EPS, net margin
  P/E on the latest annual EPS, dividend paid over the last 12 months and the payout ratio
  the most recent results announcement and its PDF
Writes <home>/trader/financials/<SYMBOL>.json.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import desk  # noqa: E402
import psxinfo as P  # noqa: E402


def _g(a, b):
    return (a / b - 1) if (a is not None and b not in (None, 0) and b > 0) else None


def analyse(h, cfg, symbol, c):
    fin = c.get("financials") or {}
    ann, qtr = fin.get("annual") or {}, fin.get("quarterly") or {}
    out = {"symbol": symbol, "name": c.get("name"), "sector": c.get("sector"), "price": c.get("price"),
           "fetched": c.get("fetched"), "changes": []}
    if not ann.get("periods") and not qtr.get("periods"):
        out["note"] = "no financials on the company page"
        return out

    def row(t, key, i):
        v = (t.get(key) or [])
        return v[i] if i < len(v) else None

    if qtr.get("periods"):
        ps = qtr["periods"]
        latest = ps[0]
        q = {k: row(qtr, k, 0) for k in ("Sales", "Profit after Taxation", "EPS")}
        prev = {k: row(qtr, k, 1) for k in q} if len(ps) > 1 else {}
        yago_i = next((i for i, p in enumerate(ps[1:], 1) if p.split()[0] == latest.split()[0]), None)
        yago = {k: row(qtr, k, yago_i) for k in q} if yago_i else {}
        out["quarter"] = {"period": latest, **q, "prev_period": ps[1] if len(ps) > 1 else None,
                          "year_ago_period": ps[yago_i] if yago_i else None,
                          "sales_yoy": _g(q["Sales"], yago.get("Sales")), "profit_yoy": _g(q["Profit after Taxation"], yago.get("Profit after Taxation")),
                          "eps_yoy": _g(q["EPS"], yago.get("EPS")), "eps_qoq": _g(q["EPS"], prev.get("EPS")),
                          "margin": (q["Profit after Taxation"] / q["Sales"]) if q["Sales"] else None,
                          "margin_year_ago": (yago["Profit after Taxation"] / yago["Sales"]) if yago.get("Sales") else None}
    if ann.get("periods"):
        a0 = {k: row(ann, k, 0) for k in ("Sales", "Profit after Taxation", "EPS")}
        a1 = {k: row(ann, k, 1) for k in a0}
        out["year"] = {"period": ann["periods"][0], **a0, "prev_period": ann["periods"][1] if len(ann["periods"]) > 1 else None,
                       "sales_growth": _g(a0["Sales"], a1["Sales"]), "profit_growth": _g(a0["Profit after Taxation"], a1["Profit after Taxation"]),
                       "eps_growth": _g(a0["EPS"], a1["EPS"]),
                       "margin": (a0["Profit after Taxation"] / a0["Sales"]) if a0["Sales"] else None,
                       "margin_prev": (a1["Profit after Taxation"] / a1["Sales"]) if a1.get("Sales") else None}
        if c.get("price") and a0["EPS"]:
            out["pe_latest_year"] = c["price"] / a0["EPS"] if a0["EPS"] > 0 else None
    out["pe_page"] = c.get("pe")
    div = P.dividend_summary(cfg, symbol, c, P.load_payouts(h), price=c.get("price"))
    out["dps_ttm"] = div.get("dps_ttm")
    out["yield_ttm"] = div.get("yield_ttm")
    if out.get("year", {}).get("EPS") and div.get("dps_ttm"):
        out["payout_ratio"] = div["dps_ttm"] / out["year"]["EPS"]
    res = next((a for a in c.get("announcements") or [] if a.get("tag") == "results"
                and "result" in a["title"].lower()), None)
    out["latest_results"] = res
    # what changed, in words
    ch = out["changes"]
    q = out.get("quarter")
    if q and q.get("eps_yoy") is not None:
        ch.append("%s EPS %.2f, %s on %s (%s)" % (q["period"], q["EPS"], _word(q["eps_yoy"]), q["year_ago_period"],
                                                  C.fmt_pct(q["eps_yoy"])))
    if q and q.get("sales_yoy") is not None:
        ch.append("%s sales %s year on year (%s)" % (q["period"], _word(q["sales_yoy"]), C.fmt_pct(q["sales_yoy"])))
    if q and q.get("margin") is not None and q.get("margin_year_ago") is not None:
        d = q["margin"] - q["margin_year_ago"]
        ch.append("net margin %.1f%% vs %.1f%% a year ago (%s)" % (100 * q["margin"], 100 * q["margin_year_ago"],
                                                                 "wider" if d > 0.005 else "narrower" if d < -0.005 else "about the same"))
    y = out.get("year")
    if y and y.get("eps_growth") is not None:
        ch.append("full year %s: EPS %.2f (%s), profit %s, sales %s" % (y["period"], y["EPS"], C.fmt_pct(y["eps_growth"]),
                                                                       C.fmt_pct(y["profit_growth"]), C.fmt_pct(y["sales_growth"])))
    if out.get("payout_ratio"):
        ch.append("paid Rs %.2f a share in dividends over 12 months: %.0f%% of the latest annual EPS" % (
            out["dps_ttm"], 100 * out["payout_ratio"]))
    return out


def _word(g):
    return "up" if g > 0.02 else "down" if g < -0.02 else "flat"


def _m(v):
    """Thousands of rupees -> 'Rs 449.2bn'."""
    if v is None:
        return "n/a"
    r = v * 1000
    for unit, d in (("tn", 1e12), ("bn", 1e9), ("m", 1e6)):
        if abs(r) >= d:
            return "Rs %.1f%s" % (r / d, unit)
    return "Rs {:,.0f}".format(r)


def show(r):
    lines = ["%s  %s  [%s]%s" % (r["symbol"], r.get("name") or "", r.get("sector") or "",
                                 "  price %.2f" % r["price"] if r.get("price") else "")]
    if r.get("note"):
        return "\n".join(lines + ["  " + r["note"]])
    q, y = r.get("quarter"), r.get("year")
    if q:
        lines.append("  Latest quarter %s: sales %s, profit %s, EPS %.2f (vs %s: EPS %s)" % (
            q["period"], _m(q["Sales"]), _m(q["Profit after Taxation"]), q["EPS"] or 0,
            q.get("year_ago_period") or "a year ago", C.fmt_pct(q.get("eps_yoy"))))
    if y:
        lines.append("  Year %s: sales %s, profit %s, EPS %.2f (%s on %s)" % (
            y["period"], _m(y["Sales"]), _m(y["Profit after Taxation"]), y["EPS"] or 0, C.fmt_pct(y.get("eps_growth")),
            y.get("prev_period")))
    bits = []
    if r.get("pe_latest_year"):
        bits.append("P/E %.1f on that EPS" % r["pe_latest_year"])
    if r.get("yield_ttm") is not None:
        bits.append("dividend yield %s" % C.fmt_pct(r["yield_ttm"]))
    if bits:
        lines.append("  " + ", ".join(bits))
    if r["changes"]:
        lines.append("  What changed:")
        lines += ["    - " + c for c in r["changes"]]
    if r.get("latest_results"):
        lr = r["latest_results"]
        lines.append("  Latest results notice %s: %s%s" % (lr["date"], lr["title"], "\n    " + lr["pdf"] if lr.get("pdf") else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--cached", action="store_true")
    ap.add_argument("--from-file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    syms = [s.upper() for s in a.symbols]
    if a.from_file and len(syms) != 1:
        sys.exit("--from-file takes exactly one symbol")
    if not a.cached:
        import news
        failed = news.refresh(h, syms, a.from_file)
        for f in failed:
            print("couldn't refresh %s: using what's on file" % f)
    results = []
    for s in syms:
        c = P.load_company(h, s)
        if not c:
            print("%s: no company page on file (pkdata.py company %s)" % (s, s))
            continue
        r = analyse(h, cfg, s, c)
        results.append(r)
        d = os.path.join(desk.folder(h), "financials")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, s + ".json"), "w") as f:
            json.dump(r, f, indent=1)
    if a.json:
        print(json.dumps(results, indent=1))
        return 0
    for r in results:
        print(show(r) + "\n")
    if len(results) > 1:
        print(C.md_table(["Stock", "Quarter", "EPS", "EPS y/y", "Sales y/y", "Year EPS", "EPS growth", "P/E", "Yield"],
                         [[r["symbol"], (r.get("quarter") or {}).get("period", ""), "%.2f" % ((r.get("quarter") or {}).get("EPS") or 0),
                           C.fmt_pct((r.get("quarter") or {}).get("eps_yoy")), C.fmt_pct((r.get("quarter") or {}).get("sales_yoy")),
                           "%.2f" % ((r.get("year") or {}).get("EPS") or 0), C.fmt_pct((r.get("year") or {}).get("eps_growth")),
                           "%.1f" % r["pe_latest_year"] if r.get("pe_latest_year") else "n/a", C.fmt_pct(r.get("yield_ttm"))]
                          for r in results]))
    print("Figures from the PSX portal (data by Capital Stake, possibly standardised): check the results PDF. "
          "Not investment advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
