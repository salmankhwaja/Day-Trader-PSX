#!/usr/bin/env python3
"""Get PSX prices and MUFAP fund data into local files.

  pkdata.py psx SYMBOL [SYMBOL ...]          download daily prices from the PSX data portal
  pkdata.py psx --watchlist                  ... for every symbol in config.json, plus the benchmark
  pkdata.py psx SYMBOL --from-file raw.json  parse a response you saved yourself (or a CSV)
  pkdata.py mufap                            download today's MUFAP performance summary
  pkdata.py mufap --from-file page.md        parse a saved copy (HTML or Markdown)
  pkdata.py status                           what data is on disk and how fresh it is

Sources
  PSX    https://dps.psx.com.pk/timeseries/eod/<SYMBOL>  JSON, about five years of daily
         [unix_time, close, volume, open] rows (undocumented; checked on parse).
         Index symbols such as KSE100 are reported to work the same way.
  MUFAP  https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=1  the daily NAV and
         return table for every open-end fund, grouped by category.

When a direct download is blocked (the Claude phone app's sandbox blocks most sites),
fetch the same URL with any web tool you have, save the body to a file and use --from-file.
The parsers accept the raw JSON, HTML, or a Markdown rendering of the page.

PSX restricts redistribution of its market data. These files are for your own analysis:
keep them out of public repositories.
"""
import argparse
import csv
import datetime as dt
import html.parser
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

PSX_EOD = "https://dps.psx.com.pk/timeseries/eod/%s"
MUFAP_URL = "https://www.mufap.com.pk/Industry/IndustryStatDaily?tab=1"
PKT = dt.timedelta(hours=5)  # Pakistan Standard Time, no daylight saving

MUFAP_PERIODS = ["ytd", "mtd", "d1", "d15", "d30", "d90", "d180", "d270", "d365", "y2", "y3"]


# ---------------------------------------------------------------- PSX

def parse_psx(text):
    """Rows {date, open, close, volume} from the PSX EOD JSON, or from a CSV with a header."""
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        obj = json.loads(text)
        data = obj.get("data", obj) if isinstance(obj, dict) else obj
        rows = []
        for r in data or []:
            if not isinstance(r, (list, tuple)) or len(r) < 2:
                continue
            ts, close = r[0], r[1]
            if close in (None, "") or ts in (None, ""):
                continue
            ts = float(ts)
            if ts > 1e12:  # milliseconds
                ts /= 1000.0
            day = (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=ts) + PKT).date()
            close = float(close)
            vol = float(r[2]) if len(r) > 2 and r[2] not in (None, "") else 0.0
            op = float(r[3]) if len(r) > 3 and r[3] not in (None, "", 0) else close
            rows.append({"date": day.isoformat(), "open": op, "close": close, "volume": vol})
        return rows
    # CSV fallback: needs date and close columns, case-insensitive.
    reader = csv.DictReader(text.splitlines())
    keys = {k.lower().strip(): k for k in (reader.fieldnames or [])}
    if "date" not in keys or "close" not in keys:
        raise ValueError("not PSX JSON, and the CSV has no date/close columns")
    rows = []
    for r in reader:
        try:
            close = float(r[keys["close"]].replace(",", ""))
        except ValueError:
            continue
        d = _parse_date(r[keys["date"]])
        if not d:
            continue
        op = r.get(keys.get("open", ""), "") if "open" in keys else ""
        vol = r.get(keys.get("volume", ""), "") if "volume" in keys else ""
        rows.append({"date": d, "open": float(op.replace(",", "")) if op else close,
                     "close": close, "volume": float(vol.replace(",", "")) if vol else 0})
    return rows


def cmd_psx(a, h, cfg):
    symbols = [s.upper() for s in a.symbols]
    if a.watchlist:
        symbols += [s.upper() for s in cfg["watchlist"]] + [cfg["benchmark"].upper()]
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        sys.exit("name at least one symbol, or use --watchlist")
    if a.from_file and len(symbols) != 1:
        sys.exit("--from-file takes exactly one symbol")
    failed = []
    for s in symbols:
        try:
            if a.from_file:
                with open(a.from_file, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            else:
                text = C.http_get(PSX_EOD % s)
            rows = parse_psx(text)
            if not rows:
                raise ValueError("no price rows in the response")
            path = C.price_path(h, s)
            if os.path.exists(path):  # merge with what we already have
                rows = C.read_prices(path) + rows
            rows = C.write_prices(path, rows)
            print("%-8s %5d days  %s .. %s  last close %.2f" % (
                s, len(rows), rows[0]["date"], rows[-1]["date"], rows[-1]["close"]))
            jumps = [rows[i]["date"] for i in range(1, len(rows))
                     if rows[i - 1]["close"] and rows[i]["close"] / rows[i - 1]["close"] < 0.7]
            if jumps:  # PSX circuit breakers cap a normal day well above this
                print("         warning: fell 30%%+ in one day on %s; likely a bonus issue, split "
                      "or rights adjustment, which distorts returns" % ", ".join(jumps[-3:]))
        except Exception as e:  # keep going through the list
            failed.append(s)
            print("%-8s FAILED: %s" % (s, e))
    if failed:
        print("\n%d failed: %s. If the site is blocked here, fetch %s with a web tool, "
              "save it, and rerun with --from-file." % (len(failed), " ".join(failed), PSX_EOD % "<SYMBOL>"))
        return 1
    return 0


# ---------------------------------------------------------------- MUFAP

class _Tables(html.parser.HTMLParser):
    """Collects every <tr> as a list of cell texts."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _rows_from_text(text):
    if "<tr" in text.lower():
        p = _Tables()
        p.feed(text)
        return p.rows
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and not re.match(r"^\|[\s\-|:]+\|$", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append([re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c) for c in cells])
    return rows


def _parse_date(s):
    s = (s or "").strip()
    for f in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d %b %Y", "%b %d %Y"):
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None


def _num(s):
    s = (s or "").replace(",", "").replace("%", "").strip()
    neg = s.startswith("(") and s.endswith(")")  # accounting style: (3.13) means -3.13
    if neg:
        s = s[1:-1].strip()
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return None


CAT_RE = re.compile(r"^(.*?)\s*\(\s*(Absolute|Annualized)\s+Return\s*\)\s*$", re.I)


def parse_mufap(text):
    """(report_date, funds) from the MUFAP performance summary page.

    Each fund: category, return_type ('absolute' or 'annualized'), fund, rating,
    validity_date, nav and the return columns in MUFAP_PERIODS (percent, None for N/A).
    """
    m = re.search(r"Report Date:\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})", text)
    report_date = _parse_date(m.group(1)) if m else None
    funds, category, rtype = [], None, None
    for cells in _rows_from_text(text):
        cells = [c for c in cells]
        if len(cells) == 1 or (len(cells) > 1 and all(not c for c in cells[1:])):
            cm = CAT_RE.match(cells[0])
            if cm:  # a category heading row (the summary list carries a count after it; skip those)
                category, rtype = cm.group(1).strip(), cm.group(2).lower()
            continue
        if len(cells) < 17 or cells[0].lower() in ("sector", "") or category is None:
            continue
        c = cells[-17:]  # sector, fund, rating, benchmark, validity, nav, 11 return columns
        nav = _num(c[5])
        if nav is None:
            continue
        f = {"category": category, "return_type": rtype, "fund": c[1], "rating": c[2],
             "validity_date": _parse_date(c[4]) or report_date, "nav": nav}
        for k, v in zip(MUFAP_PERIODS, c[6:17]):
            f[k] = _num(v)
        funds.append(f)
    return report_date, funds


def save_mufap(h, report_date, funds):
    d = os.path.join(h, "mufap")
    os.makedirs(d, exist_ok=True)
    report_date = report_date or dt.date.today().isoformat()
    snap = os.path.join(d, report_date + ".csv")
    cols = ["category", "return_type", "fund", "rating", "validity_date", "nav"] + MUFAP_PERIODS
    with open(snap, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in funds:
            w.writerow(r)
    hist = os.path.join(d, "nav_history.csv")
    seen = {}
    if os.path.exists(hist):
        with open(hist, newline="") as f:
            for r in csv.DictReader(f):
                seen[(r["date"], r["fund"])] = r
    for r in funds:
        seen[(r["validity_date"], r["fund"])] = {"date": r["validity_date"], "fund": r["fund"],
                                                 "category": r["category"], "nav": r["nav"]}
    with open(hist, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "fund", "category", "nav"])
        w.writeheader()
        for k in sorted(seen):
            w.writerow(seen[k])
    return snap, hist


def latest_mufap(h):
    """Path of the newest MUFAP snapshot, or None."""
    d = os.path.join(h, "mufap")
    if not os.path.isdir(d):
        return None
    snaps = sorted(f for f in os.listdir(d) if re.match(r"\d{4}-\d{2}-\d{2}\.csv$", f))
    return os.path.join(d, snaps[-1]) if snaps else None


def cmd_mufap(a, h, cfg):
    if a.from_file:
        with open(a.from_file, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        try:
            text = C.http_get(MUFAP_URL)
        except Exception as e:
            sys.exit("MUFAP download failed (%s). Fetch %s with a web tool, save it, "
                     "and rerun with --from-file." % (e, MUFAP_URL))
    report_date, funds = parse_mufap(text)
    if not funds:
        sys.exit("found no fund rows. The page may be rendered by JavaScript here: save a rendered "
                 "copy (HTML or Markdown) of %s and use --from-file." % MUFAP_URL)
    snap, hist = save_mufap(h, report_date, funds)
    cats = {}
    for f in funds:
        cats[f["category"]] = cats.get(f["category"], 0) + 1
    print("MUFAP report %s: %d funds in %d categories" % (report_date, len(funds), len(cats)))
    print("saved %s and updated %s" % (snap, hist))
    return 0


def cmd_status(a, h, cfg):
    print("home: %s" % h)
    d = os.path.join(h, "psx")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            rows = C.read_prices(os.path.join(d, fn))
            if rows:
                print("  PSX %-8s %5d days, last %s" % (fn[:-4], len(rows), rows[-1]["date"]))
    snap = latest_mufap(h)
    print("  MUFAP latest snapshot: %s" % (os.path.basename(snap)[:-4] if snap else "none"))
    p = os.path.join(h, "paper", "portfolio.json")
    print("  paper portfolio: %s" % ("yes" if os.path.exists(p) else "not started"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="data folder (default ./pkmarket or $PKM_HOME)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("psx")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--watchlist", action="store_true")
    p.add_argument("--from-file")
    p = sub.add_parser("mufap")
    p.add_argument("--from-file")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    cfg = C.load_config(h)
    return {"psx": cmd_psx, "mufap": cmd_mufap, "status": cmd_status}[a.cmd](a, h, cfg)


if __name__ == "__main__":
    sys.exit(main())
