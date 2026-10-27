#!/usr/bin/env python3
"""The daily pipeline, in plain Python so it runs anywhere: Linux, macOS, Windows, and Android
(Pydroid 3 or Termux). daily_sync.sh and the systemd timer call this.

  daily.py                       watchlist: data, paper account, your portfolio, dashboard
  daily.py --scope all           every listed share (first run 15-20 minutes)
  daily.py --no-download         skip downloads; recompute advice and rebuild the dashboard
  daily.py --log FILE            also append the output to FILE

Steps, each one allowed to fail without stopping the rest:
  1. universe + Shariah list (Mondays, or when missing)
  2. company pages (7-day cache), prices, the market watch (every share's last trade), payouts, MUFAP
  3. paper account: credit dividends, review, record the value, a fresh proposal on Fridays
  4. your portfolio: list dividends due (never recorded automatically), advice with stop-losses,
     fund review
  5. rebuild the dashboard (also a one-file copy, dashboard.html, to open on a phone)
  6. with PKM_GIT_PUSH=1 and a git repo as the data folder: commit and push (your PRIVATE repo)

Nothing here places an order or books a trade in your real portfolio.
"""
import argparse
import contextlib
import datetime as dt
import io
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C  # noqa: E402


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def step(name, module, argv, home):
    """Run `module.main(argv)` in this process; report and swallow any failure."""
    print("-- %s" % name, flush=True)
    t0 = time.time()
    try:
        mod = __import__(module)
        rc = mod.main(["--home", home] + argv)
        if rc:
            print("   (%s finished with warnings)" % name)
        if time.time() - t0 > 30:
            print("   took %s" % C._mins(time.time() - t0), flush=True)
        return True
    except SystemExit as e:
        if e.code not in (None, 0):
            print("   %s stopped: %s" % (name, e.code))
        return e.code in (None, 0)
    except Exception as e:  # keep going: one broken page must not stop the dashboard
        print("   %s failed: %s: %s" % (name, type(e).__name__, e))
        return False


def git_push(home):
    if not os.path.isdir(os.path.join(home, ".git")):
        print("PKM_GIT_PUSH=1 but %s is not a git repo; skipped" % home)
        return
    try:
        subprocess.run(["git", "add", "-A"], cwd=home, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=home).returncode == 0:
            print("no changes to push")
            return
        subprocess.run(["git", "commit", "-q", "-m", "data: %s" % dt.date.today()], cwd=home, check=True)
        subprocess.run(["git", "push", "-q"], cwd=home, check=True)
        print("pushed")
    except (OSError, subprocess.CalledProcessError) as e:
        print("git push failed: %s" % e)


def run(home, scope="watchlist", download=True, git=False):
    today = dt.date.today()
    print("== %s pipeline into %s (scope: %s)" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), home, scope))
    p = lambda *parts: os.path.join(home, *parts)  # noqa: E731
    if download:
        if not os.path.exists(p("universe.json")) or today.isoweekday() == 1:
            step("universe", "pkdata", ["universe"], home)
        whole = scope == "all" and os.path.exists(p("universe.json"))
        # watchlist pages daily (announcements change daily); the whole market weekly
        step("company pages", "pkdata", ["company", "--all"] if whole else ["company", "--watchlist", "--max-age", "1"], home)
        step("prices", "pkdata", ["psx", "--all" if whole else "--watchlist"], home)
        # one request: every listed share's last price, change and volume (the dashboard's all-shares view)
        step("market watch", "pkdata", ["live"], home)
        step("payouts", "pkdata", ["payouts"], home)
        step("mufap", "pkdata", ["mufap"], home)
        if C.load_config(home).get("pakistanibulls_terms_ok"):
            step("second opinion: PakistaniBulls", "signals", ["pakistanibulls", "--fetch"], home)
    every = ["--all"] if scope == "all" else []
    if os.path.exists(p("paper", "portfolio.json")):
        step("paper: dividends", "paper", ["dividends", "--apply"], home)
        step("paper: review", "propose", ["review", "--no-fetch"], home)
        step("paper: value", "paper", ["mark"], home)
        if today.isoweekday() == 5:
            step("paper: proposal", "propose", ["run", "--no-fetch"] + every, home)
    if os.path.exists(p("portfolio", "ledger.json")):
        step("my portfolio: dividends due", "portfolio", ["dividends"], home)
        step("my portfolio: advice", "portfolio", ["advise", "--no-fetch"] + every, home)
        step("my portfolio: funds", "funds", ["review", "--no-fetch"], home)
    step("desk: today's setups (psx-scanner)", "scanner", ["daily", "--no-fetch"] + every, home)
    step("desk: new insider dealings (psx-insiders)", "insiders", ["--new", "--cached"], home)
    step("dashboard", "dashboard", ["build"], home)
    step("dashboard (one file)", "dashboard", ["build", "--standalone", p("dashboard.html")], home)
    if git:
        git_push(home)
    print("== done %s" % dt.datetime.now().strftime("%H:%M"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home")
    ap.add_argument("--scope", choices=["watchlist", "all"], default=os.environ.get("PKM_SCOPE", "watchlist"))
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    h = C.home(a.home)
    git = os.environ.get("PKM_GIT_PUSH") == "1"
    if a.log:
        with open(a.log, "a", encoding="utf-8") as f, contextlib.redirect_stdout(Tee(sys.stdout, f)):
            run(h, a.scope, not a.no_download, git)
    else:
        run(h, a.scope, not a.no_download, git)
    return 0


if __name__ == "__main__":
    sys.exit(main())
