"""The trading desk's shared files: what one psx-* skill writes, the next one reads.

All of them live in <home>/trader/ (default ~/pkmarket/trader/), next to the prices and your
portfolio ledger, so the skills work together however you call them:

  setups.json        psx-scanner      today's candidates (daily setups, opening-range breakouts, movers)
  news.json          psx-news         recent announcements on the shares you follow
  plan.json          psx-exit         the trade: entry, stop, target, flat-by time, setup
  entry.json         psx-entry        the last check of a setup: waiting / triggered / expired
  timemachine.json   psx-timemachine  the replay's odds for the plan
  orders.json        psx-budget       the sized bracket: buy, stop-loss, take-profit
  risk.json          psx-risk         PASS / BLOCK for each order, with a fingerprint of it
  tickets.json       psx-broker       tickets shown to you, and the fills you confirmed
  alerts.json        psx-alerts       price, stop, target and clock alerts, and which have rung
  insiders.json      psx-insiders     directors' and sponsors' share dealings found
  financials/        psx-analyst      the latest results summaries

Nothing in this folder is ever sent to a broker: there is no order API on PSX retail apps, and
these tools would not use one.
"""
import datetime as dt
import hashlib
import json
import os

import common as C


def folder(h):
    d = os.path.join(h, "trader")
    os.makedirs(d, exist_ok=True)
    return d


def path(h, name):
    return os.path.join(folder(h), name)


def read(h, name, default=None):
    try:
        with open(path(h, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write(h, name, data):
    with open(path(h, name), "w") as f:
        json.dump(data, f, indent=1, default=str)
    return path(h, name)


def now(arg=None):
    """Pakistan time, or the --now the user pinned ("YYYY-MM-DD HH:MM") for replays and tests."""
    return dt.datetime.fromisoformat(arg) if arg else C.pk_now()


def setting(cfg, key):
    """A risk-style variable (profiles.py), as a float."""
    import profiles
    v = cfg.get(key)
    return float(v if v is not None else profiles.PROFILES[profiles.DEFAULT_PROFILE][key])


def capital(h, cfg):
    """(capital, cash): portfolio value plus recorded cash, else config "capital"."""
    try:
        import portfolio as PF
        s = PF.summary(h, PF.load(h))
        total = s["value"] + (s["cash"] or 0)
        if total:
            return total, s["cash"]
    except Exception:  # noqa: BLE001 -- no ledger yet
        pass
    cap = float(cfg.get("capital") or 0)
    return cap, (cap or None)


def held(h):
    """{symbol: qty} of shares you hold now (the portfolio ledger)."""
    try:
        import portfolio as PF
        return {p["symbol"]: p["qty"] for p in PF.holdings(h, PF.load(h))}
    except Exception:  # noqa: BLE001
        return {}


def fingerprint(order):
    """A short hash of the parts of an order that matter, so a verdict can't be reused for another."""
    keys = ("symbol", "side", "type", "qty", "limit", "trigger")
    blob = json.dumps({k: order.get(k) for k in keys}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def last_close(h, symbol):
    """(date, close) of the newest end-of-day price on file, or (None, None)."""
    p = C.price_path(h, symbol)
    if not os.path.exists(p):
        return None, None
    rows = C.read_prices(p, live=False)
    return (rows[-1]["date"], rows[-1]["close"]) if rows else (None, None)


DISCLAIMER = ("Rule-based, from public PSX data; not investment advice. Most people who day trade lose money. "
              "Nothing here places an order: you decide, and you type it into your broker's app.")
