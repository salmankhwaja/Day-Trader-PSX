#!/usr/bin/env python3
"""Decide whether the price feed should run now, from feed-settings.json. Standard library only.

GitHub can't read schedule times from a file, so the workflow wakes every 30 minutes and asks this
script. It looks for the most recent time in `runs` that has come (within `catch_up_hours`, so a
run GitHub delayed or dropped still happens) and prints, for the workflow:

  slot=2026-11-03T13:07+05:00   the scheduled time this run is for (the workflow remembers which
                                slots ran, so each runs once, however many checks see it)
  mode=normal | mufap-only      psx+mufap, or mufap only
  run=true | false
  fetch_timeout=11  job_timeout=15

A manual run (Run workflow) always runs, with the mode chosen there, except mode "check": that one
decides exactly like a scheduled check. It is for an outside timer (cron-job.org and the like, see
docs/REFERENCE.md) when GitHub's own schedule is late or skips runs.

  python3 tools/feed_plan.py                       # what a check would do now
  python3 tools/feed_plan.py --now 2026-11-03T13:20 # ... at that Pakistan time
  python3 tools/feed_plan.py --list                # every run in the coming week
"""
import argparse
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS = os.path.join(ROOT, "feed-settings.json")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULTS = {"enabled": True, "utc_offset_hours": 5, "runs": [], "catch_up_hours": 6, "fetch_timeout_minutes": 11,
            "backfill_timeout_minutes": 38, "company_pages_seconds": 240, "company_pages_seconds_backfill": 600,
            "company_retry_days": 7, "history_months": 13}


def load(path=SETTINGS):
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
    except FileNotFoundError:
        user = {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in user.items() if not k.startswith("about")})
    return cfg


def days_of(spec):
    """'mon-fri', 'sat', 'mon,wed,fri', 'daily' -> set of weekday numbers (Monday = 0)."""
    spec = str(spec).strip().lower()
    if spec in ("daily", "every day", "all", "*"):
        return set(range(7))
    out = set()
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            i, j = DAYS.index(a[:3]), DAYS.index(b[:3])
            k = i
            while True:
                out.add(k)
                if k == j:
                    break
                k = (k + 1) % 7
        elif part:
            out.add(DAYS.index(part[:3]))
    return out


def check(cfg):
    """A list of problems with the settings (empty when fine)."""
    bad = []
    for i, r in enumerate(cfg["runs"]):
        try:
            days_of(r.get("days", ""))
        except ValueError:
            bad.append("runs[%d].days %r: use mon..sun, ranges like mon-fri, or daily" % (i, r.get("days")))
        for t in r.get("at") or []:
            try:
                h, m = map(int, str(t).split(":"))
                assert 0 <= h < 24 and 0 <= m < 60
            except (ValueError, AssertionError):
                bad.append("runs[%d].at %r: use HH:MM, 24-hour" % (i, t))
        if r.get("fetch", "psx+mufap") not in ("psx+mufap", "mufap"):
            bad.append("runs[%d].fetch %r: psx+mufap or mufap" % (i, r.get("fetch")))
    for k in ("fetch_timeout_minutes", "backfill_timeout_minutes"):
        if not (1 <= float(cfg[k]) <= 340):
            bad.append("%s must be between 1 and 340 minutes" % k)
    return bad


def slots(cfg, start, end):
    """[(datetime, fetch)] scheduled between start and end (aware datetimes), oldest first."""
    tz = start.tzinfo
    out = []
    d = start.date() - dt.timedelta(days=1)
    while d <= end.date():
        for r in cfg["runs"]:
            if d.weekday() in days_of(r.get("days", "")):
                for t in r.get("at") or []:
                    h, m = map(int, str(t).split(":"))
                    s = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
                    if start <= s <= end:
                        out.append((s, r.get("fetch", "psx+mufap")))
        d += dt.timedelta(days=1)
    return sorted(out)


def plan(cfg, now, event="schedule", manual_mode=None, run_id="0"):
    fetch_t = int(cfg["fetch_timeout_minutes"])
    out = {"run": "false", "mode": "", "slot": "", "fetch_timeout": str(fetch_t), "job_timeout": str(fetch_t + 4), "why": "",
           "scheduled": "false"}
    if event == "workflow_dispatch" and manual_mode == "check":
        event = "schedule"
    if event == "workflow_dispatch":
        mode = manual_mode or "normal"
        if mode == "backfill":
            fetch_t = int(cfg["backfill_timeout_minutes"])
        out.update(run="true", mode=mode, slot="manual-" + str(run_id), fetch_timeout=str(fetch_t),
                   job_timeout=str(fetch_t + 4), why="started by hand")
        return out
    out["scheduled"] = "true"
    if not cfg["enabled"]:
        out["why"] = "feed-settings.json has enabled: false"
        return out
    due = slots(cfg, now - dt.timedelta(hours=float(cfg["catch_up_hours"])), now)
    if not due:
        out["why"] = "no scheduled time in the last %s hours" % cfg["catch_up_hours"]
        return out
    s, fetch = due[-1]
    out.update(run="true", slot=s.isoformat(timespec="minutes"), mode="mufap-only" if fetch == "mufap" else "normal",
               why="scheduled for %s (%s)" % (s.strftime("%a %H:%M"), fetch))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", help="a Pakistan time to plan for, YYYY-MM-DDTHH:MM (default: now)")
    ap.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", "schedule"))
    ap.add_argument("--mode", default=os.environ.get("MANUAL_MODE") or None)
    ap.add_argument("--list", action="store_true", help="every scheduled run in the next 7 days")
    a = ap.parse_args(argv)
    cfg = load()
    bad = check(cfg)
    if bad:
        print("feed-settings.json has problems:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    tz = dt.timezone(dt.timedelta(hours=float(cfg["utc_offset_hours"])))
    now = dt.datetime.fromisoformat(a.now).replace(tzinfo=tz) if a.now else dt.datetime.now(tz)
    if a.list:
        for s, fetch in slots(cfg, now, now + dt.timedelta(days=7)):
            print("%s  %s" % (s.strftime("%a %d %b %H:%M"), fetch))
        return 0
    out = plan(cfg, now, a.event, a.mode, os.environ.get("GITHUB_RUN_ID", "0"))
    for k, v in out.items():
        print("%s=%s" % (k, v))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for k, v in out.items():
                f.write("%s=%s\n" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
