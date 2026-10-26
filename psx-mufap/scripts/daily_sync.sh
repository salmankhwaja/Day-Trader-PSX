#!/usr/bin/env bash
# Daily pipeline for a computer with normal internet (e.g. Linux Mint). Run it at any time you
# like (install_services.sh sets the schedule): it always works from the latest published close.
#
#   ./daily_sync.sh                       watchlist mode (fast), data in ~/pkmarket
#   PKM_SCOPE=all ./daily_sync.sh         every listed share (first run ~20 min)
#   PKM_HOME=/somewhere/else ./daily_sync.sh
#
# Steps: universe + Shariah list (weekly), company pages / dividends (weekly cache), latest
# payouts, prices, MUFAP, credit paper dividends, review open positions, record the account
# value, your real portfolio's advice (sell/hold/buy with stop-losses), rebuild the dashboard.
# Optional: with PKM_GIT_PUSH=1 and PKM_HOME a git repo, commit and push it (e.g. to your
# own PRIVATE repo, so Claude on your phone can read fresh data).
# Proposals are generated but NEVER booked automatically: you approve them (propose.py run --apply).
#
# Never push the data folder to a public repo: PSX does not allow its market data to be republished.
# Scheduling: install_services.sh (systemd timer, PKM_SCHEDULE="07:00,04:00"), or cron, e.g.
# 07:00 and 04:00 Mon-Fri, if the computer's clock is on Pakistan time:
#   0 7,4 * * 1-5  /path/to/daily_sync.sh >> $HOME/pkmarket-sync.log 2>&1
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${PKM_HOME:=$HOME/pkmarket}"
: "${PKM_GIT_PUSH:=0}"
: "${PKM_SCOPE:=watchlist}"
export PKM_HOME
mkdir -p "$PKM_HOME"
py() { python3 "$HERE/$1" "${@:2}"; }
step() { echo "-- $*"; }
echo "== $(date '+%F %T') pipeline into $PKM_HOME (scope: $PKM_SCOPE)"

# Universe and Shariah list: refresh on Mondays, or when missing.
if [ ! -f "$PKM_HOME/universe.json" ] || [ "$(date +%u)" = "1" ]; then
  step universe; py pkdata.py universe || echo "universe failed"
fi
if [ "$PKM_SCOPE" = "all" ] && [ -f "$PKM_HOME/universe.json" ]; then
  step company pages; py pkdata.py company --all || echo "some company pages failed"
  step prices; py pkdata.py psx --all || echo "some symbols failed"
else
  step company pages; py pkdata.py company --watchlist || echo "some company pages failed"
  step prices; py pkdata.py psx --watchlist || echo "some symbols failed"
fi
step payouts; py pkdata.py payouts || echo "payouts failed"
step mufap; py pkdata.py mufap || echo "MUFAP failed"

if [ -f "$PKM_HOME/paper/portfolio.json" ]; then
  step paper dividends; py paper.py dividends --apply
  step review; py propose.py review          # prints SELL suggestions; does not act
  step mark; py paper.py mark
  if [ "$(date +%u)" = "5" ]; then           # Fridays: a fresh proposal to look at
    step proposal
    if [ "$PKM_SCOPE" = "all" ]; then py propose.py run --all; else py propose.py run; fi
  fi
fi
if [ -f "$PKM_HOME/portfolio/ledger.json" ]; then
  step my portfolio: dividends due     # listed for you to confirm, never recorded automatically
  py portfolio.py dividends
  step my portfolio: advice            # sell/hold with stops, buy ideas with stops and size
  if [ "$PKM_SCOPE" = "all" ]; then py portfolio.py advise --all; else py portfolio.py advise; fi
  step my portfolio: funds             # HOLD / REVIEW for the mutual funds you hold
  py funds.py review
fi
step dashboard; py dashboard.py build

if [ "$PKM_GIT_PUSH" = "1" ] && [ -d "$PKM_HOME/.git" ]; then
  cd "$PKM_HOME"
  git add -A
  if ! git diff --cached --quiet; then
    git commit -q -m "data: $(date +%F)" && git push -q && echo "pushed"
  else
    echo "no changes"
  fi
fi
echo "== done $(date '+%T')"
