"""PSX company data: the full listed universe, sectors, Shariah status and dividends.

Pages read (all public pages of the PSX Data Portal):
  https://dps.psx.com.pk/indices/ALLSHR      every listed share (KSE All Share Index)
  https://dps.psx.com.pk/indices/KMIALLSHR   every Shariah-compliant share (KMI All Share)
  https://dps.psx.com.pk/company/<SYMBOL>    sector, P/E, 52-week range, market cap, free
                                             float, and the full payouts (dividend) history
  https://dps.psx.com.pk/payouts             the latest dividend announcements, market-wide

Files written under <home>:
  universe.json                 {symbol: {name, price, shares_m, mcap_m, shariah, tags}}
  companies/<SYMBOL>.json       one company page, parsed
  payouts.json                  latest market-wide announcements

Payout notation on PSX: "60% (F) (D)" is a cash dividend of 60% of face value, final;
(i)/(ii)/(iii) are 1st/2nd/3rd interim; (B) is bonus shares; (R) is a rights issue.
Dividend per share = percent x face value / 100. Face value is not on the page: it is
Rs 10 for most PSX shares, set exceptions in config.json "face_values": {"SYM": 5}.
"""
import datetime as dt
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

BASE = "https://dps.psx.com.pk"
INDEX_URL = BASE + "/indices/%s"
COMPANY_URL = BASE + "/company/%s"
PAYOUTS_URL = BASE + "/payouts"


def _text(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def _num(s):
    s = (s or "").replace(",", "").replace("%", "").replace("Rs.", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _table_rows(fragment):
    """[[cell html, ...], ...] for each <tr> in the body of a table."""
    out = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", fragment, flags=re.S | re.I):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.S | re.I)  # header rows have none
        if cells:
            out.append(cells)
    return out


def _dmy(s):
    try:
        return dt.datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _announce_date(s):
    s = _text(s)
    for f in ("%B %d, %Y %I:%M %p", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    m = re.match(r"([A-Za-z]+ \d{1,2}, \d{4})", s)
    if m:
        try:
            return dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            return None
    return None


# ------------------------------------------------------------------ index pages

def parse_index(text):
    """{symbol: {name, price, shares_m, mcap_m, tags}} from an /indices/<NAME> page or fragment."""
    out = {}
    for cells in _table_rows(text):
        if len(cells) < 11:
            continue
        first = _text(cells[0]).split()
        if not first or not re.match(r"^[A-Z0-9][A-Z0-9\-]*$", first[0]):
            continue
        sym = first[0]
        price = _num(_text(cells[3])) or _num(_text(cells[2]))
        out[sym] = {"name": _text(cells[1]), "price": price,
                    "shares_m": _num(_text(cells[9])), "mcap_m": _num(_text(cells[10])),
                    "tags": first[1:]}
    return out


def build_universe(allshr_text, kmi_text):
    allshr, kmi = parse_index(allshr_text), parse_index(kmi_text)
    uni = {}
    for s, v in allshr.items():
        v = dict(v)
        v["shariah"] = s in kmi
        uni[s] = v
    for s, v in kmi.items():  # in KMI but somehow missing from ALLSHR
        if s not in uni:
            v = dict(v)
            v["shariah"] = True
            uni[s] = v
    return uni


def load_universe(h):
    p = os.path.join(h, "universe.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


# ------------------------------------------------------------------ company page

PAYOUT_RE = re.compile(r"([\d.]+)\s*%\s*((?:\([^)]*\)\s*)*?)\(([DBR])\)", re.I)


def parse_payout_details(s):
    """'60% (F) (D)' -> {'cash_pct': 60.0, 'bonus_pct': 0, 'right_pct': 0, 'kind': 'final'}."""
    d = {"cash_pct": 0.0, "bonus_pct": 0.0, "right_pct": 0.0, "kind": ""}
    for pct, mid, typ in PAYOUT_RE.findall(s or ""):
        key = {"D": "cash_pct", "B": "bonus_pct", "R": "right_pct"}[typ.upper()]
        d[key] += float(pct)
        m = mid.lower()
        if "(f)" in m:
            d["kind"] = "final"
        elif re.search(r"\((i{1,3}|iv)\)", m):
            d["kind"] = "interim " + re.search(r"\((i{1,3}|iv)\)", m).group(1)
    return d


def parse_company(text, symbol=None):
    c = {"symbol": symbol, "fetched": dt.date.today().isoformat()}
    m = re.search(r'class="quote__name">(.*?)<div', text, flags=re.S)
    c["name"] = _text(m.group(1)) if m else None
    blk = text[text.find('class="quote__name"'):text.find('class="quote__sector"')] if m else ""
    c["tags"] = [_text(t) for t in re.findall(r'class="tag[^"]*">([^<]*)<', blk)]  # e.g. XD = ex-dividend
    m = re.search(r'class="quote__sector">\s*<span>(.*?)</span>', text, flags=re.S)
    c["sector"] = _text(m.group(1)) if m else None
    m = re.search(r'class="quote__close">(.*?)</div>', text, flags=re.S)
    c["price"] = _num(_text(m.group(1))) if m else None
    stats = {}
    for label, value in re.findall(
            r'class="stats_label">(.*?)</div>\s*<div class="stats_value[^"]*">(.*?)</div>', text, flags=re.S):
        label, value = _text(label), _text(value)
        stats.setdefault(label, value)  # first occurrence: the regular market, not futures tabs
        if label == "Free Float" and value.endswith("%"):
            stats["Free Float %"] = value
    rng = stats.get("52-WEEK RANGE ^", "")
    lo_hi = re.findall(r"[\d,.]+", rng)
    c["low_52w"] = _num(lo_hi[0]) if len(lo_hi) > 0 else None
    c["high_52w"] = _num(lo_hi[1]) if len(lo_hi) > 1 else None
    c["pe"] = _num(stats.get("P/E Ratio (TTM) **"))
    c["change_1y_pct"] = _num(stats.get("1-Year Change * ^"))
    c["change_ytd_pct"] = _num(stats.get("YTD Change * ^"))
    mc = next((v for k, v in stats.items() if k.startswith("Market Cap")), None)
    c["mcap_m"] = _num(mc) / 1000.0 if _num(mc) is not None else None  # page shows thousands
    c["shares"] = _num(stats.get("Shares"))
    c["free_float_pct"] = _num(stats.get("Free Float %"))
    payouts = []
    i = text.find('id="payouts"')
    if i >= 0:
        seg = text[i:text.find("</table>", i)]
        for cells in _table_rows(seg):
            if len(cells) < 4:
                continue
            bc = re.findall(r"\d{2}/\d{2}/\d{4}", _text(cells[3]))
            p = {"announced": _announce_date(cells[0]), "period": _text(cells[1]),
                 "details": _text(cells[2]),
                 "bc_from": _dmy(bc[0]) if bc else None, "bc_to": _dmy(bc[-1]) if bc else None}
            p.update(parse_payout_details(p["details"]))
            payouts.append(p)
    c["payouts"] = payouts
    c["announcements"] = parse_announcements(text)
    c["financials"] = parse_financials(text)
    return c


# ------------------------------------------------------------------ announcements and financials

# What an announcement is about, from its title (first match wins; checked in this order).
ANNOUNCE_TAGS = [
    ("results", r"financial result|quarterly report|half yearly report|annual report|accounts"),
    ("payout", r"dividend|bonus|right(?:s)? (?:issue|shares)|book closure|entitlement|payout"),
    ("board", r"board meeting|closed period"),
    ("meeting", r"general meeting|\bagm\b|\beogm\b|\begm\b|resolutions passed"),
    ("deal", r"acqui|merger|amalgamation|scheme of arrangement|tender offer|public offer|delist|buy-?back"),
    ("material", r"material information|price sensitive"),
]


INSIDER_WHO = r"director|chief executive|\bceo\b|\bcfo\b|executive|sponsor|substantial|beneficial|insider|disclosure of interest"
INSIDER_WHAT = (r"transaction|purchase|sale\b|selling|buying|acqui|dispos|dealing|disclosure of interest|"
                r"change in (?:share)?holding|section 102")


def classify(title, tab=None):
    low = (title or "").lower()
    if re.search(INSIDER_WHO, low) and re.search(INSIDER_WHAT, low):
        return "insider"
    for tag, rx in ANNOUNCE_TAGS:
        if re.search(rx, low):
            return tag
    if tab == "Financial Results":
        return "results"
    if tab == "Board Meetings":
        return "board"
    return "other"


def _mdy(s):
    s = _text(s)
    for f in ("%b %d, %Y", "%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None


def parse_announcements(text):
    """[{date, title, tab, tag, pdf}] from the Announcements section of a company page (newest first)."""
    i = text.find('id="announcements"')
    if i < 0:
        return []
    end = text.find('id="financials"', i)
    seg = text[i:end if end > 0 else i + 200000]
    out = []
    for m in re.finditer(r'class="tabs__panel[^"]*"\s+data-name="([^"]+)"(.*?)</table>', seg, flags=re.S):
        tab = m.group(1)
        for cells in _table_rows(m.group(2)):
            if len(cells) < 2:
                continue
            title = _text(cells[1])
            pdf = re.search(r'href="([^"]+\.pdf)"', cells[2] if len(cells) > 2 else "")
            out.append({"date": _mdy(cells[0]), "title": title, "tab": tab, "tag": classify(title, tab),
                        "pdf": pdf.group(1) if pdf else None})
    out.sort(key=lambda a: a["date"] or "", reverse=True)
    return out


def parse_financials(text):
    """{"annual": {"periods": [...], "Sales": [...], "Profit after Taxation": [...], "EPS": [...]},
    "quarterly": {...}, "ratios": {...}} in thousands of rupees (EPS in rupees), newest period first."""
    out = {}
    i = text.find('id="financials"')
    if i >= 0:
        seg = text[i:text.find('id="ratios"', i) if text.find('id="ratios"', i) > 0 else i + 100000]
        for m in re.finditer(r'class="tabs__panel[^"]*"\s+data-name="([^"]+)"(.*?)</table>', seg, flags=re.S):
            out[m.group(1).lower()] = _fin_table(m.group(2))
    j = text.find('id="ratios"')
    if j >= 0:
        out["ratios"] = _fin_table(text[j:text.find("</table>", j)])
    return out


def _fin_table(fragment):
    periods = [_text(h) for h in re.findall(r"<th\b[^>]*>(.*?)</th>", fragment, flags=re.S)][1:]
    t = {"periods": periods}
    for cells in _table_rows(fragment):
        label = _text(cells[0])
        vals = []
        for c in cells[1:]:
            v = _text(c)
            neg = v.startswith("(") and v.endswith(")")
            n = _num(v.strip("()"))
            vals.append(-n if (neg and n is not None) else n)
        t[label] = vals
    return t


def company_path(h, symbol):
    return os.path.join(h, "companies", symbol.upper() + ".json")


def load_company(h, symbol):
    p = company_path(h, symbol)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def save_company(h, c):
    p = company_path(h, c["symbol"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(c, f, indent=1)


# ------------------------------------------------------------------ market-wide payouts

def parse_payouts_page(text):
    out = []
    for cells in _table_rows(text):
        if len(cells) < 6:
            continue
        sym = _text(cells[0]).split()
        if not sym:
            continue
        bc = re.findall(r"\d{2}/\d{2}/\d{4}", _text(cells[5]))
        p = {"symbol": sym[0], "company": _text(cells[1]), "sector": _text(cells[2]),
             "details": _text(cells[3]), "announced": _announce_date(cells[4]),
             "bc_from": _dmy(bc[0]) if bc else None, "bc_to": _dmy(bc[-1]) if bc else None}
        p.update(parse_payout_details(p["details"]))
        out.append(p)
    return out


def load_payouts(h):
    p = os.path.join(h, "payouts.json")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return json.load(f)


# ------------------------------------------------------------------ dividend summary

def face_value(cfg, symbol):
    return float((cfg.get("face_values") or {}).get(symbol.upper(), 10))


def dividend_summary(cfg, symbol, company, market_payouts=(), price=None, today=None):
    """Trailing-12-month cash dividend, yield, last payout, next known book closure, and an
    estimate of the next announcement from last year's pattern."""
    today = today or dt.date.today()
    t = today.isoformat()
    year_ago = (today - dt.timedelta(days=365)).isoformat()
    fv = face_value(cfg, symbol)
    pays = list((company or {}).get("payouts") or [])
    seen = {(p.get("announced"), p.get("details")) for p in pays}
    for p in market_payouts:  # newer announcements may not be on a cached company page yet
        if p["symbol"] == symbol and (p.get("announced"), p.get("details")) not in seen:
            pays.append(p)
    pays.sort(key=lambda p: p.get("announced") or "", reverse=True)
    cash = [p for p in pays if p.get("cash_pct")]
    ttm = sum(p["cash_pct"] * fv / 100.0 for p in cash if (p.get("announced") or "") > year_ago)
    price = price or (company or {}).get("price")
    upcoming = sorted((p for p in pays if (p.get("bc_to") or p.get("bc_from") or "") >= t),
                      key=lambda p: p.get("bc_from") or "")
    expected = None
    for p in sorted(cash, key=lambda p: p.get("announced") or ""):
        a = p.get("announced")
        if not a or a <= year_ago:
            continue
        around = dt.date.fromisoformat(a) + dt.timedelta(days=365)
        if around < today:
            continue
        # Skip if this year's equivalent (same period type, e.g. "(IQ)") is already announced.
        kind = re.sub(r"[^A-Z]", "", (p.get("period") or "").split("(")[-1])
        done = any(u is not p and (u.get("announced") or "") >= (around - dt.timedelta(days=75)).isoformat()
                   and re.sub(r"[^A-Z]", "", (u.get("period") or "").split("(")[-1]) == kind for u in cash)
        if not done:
            expected = {"around": around.isoformat(), "period_type": kind or None,
                        "last_year": p.get("details")}
            break
    last = cash[0] if cash else None
    return {
        "face_value": fv,
        "dps_ttm": round(ttm, 2),
        "yield_ttm": (ttm / price) if price and ttm else (0.0 if price else None),
        "payouts_12m": sum(1 for p in cash if (p.get("announced") or "") > year_ago),
        "last": {k: last.get(k) for k in ("announced", "details", "bc_from", "bc_to")} if last else None,
        "last_dps": round(last["cash_pct"] * fv / 100.0, 2) if last else None,
        "upcoming": [{k: p.get(k) for k in ("announced", "details", "bc_from", "bc_to", "cash_pct", "bonus_pct")}
                     for p in upcoming],
        "expected_next": expected,
    }
