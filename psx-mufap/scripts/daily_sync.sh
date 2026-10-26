#!/usr/bin/env bash
# Daily pipeline for a computer with normal internet (e.g. Linux Mint). Run after the PSX close.
#
#   ./daily_sync.sh                       watchlist mode (fast), data in ~/pkmarket
#   PKM_SCOPE=all ./daily_sync.sh         every listed share (first run ~20 min)
#   PKM_HOME=/somewhere/else ./daily_sync.sh
#
# Steps: universe + Shariah list (weekly), company pages / dividends (weekly cache), latest
# payouts, prices, MUFAP, credit paper dividends, review open positions, record the account
# value, rebuild the dashboard. Optional: with PKM_GIT_PUSH=1 and PKM_HOME a git repo, commit and
# push it (e.g. to your own PRIVATE repo, so Claude on your phone can read fresh data).
# Proposals are generated but NEVER booked automatically: you approve them (propose.py run --apply).
#
# Never push the data folder to a public repo: PSX does not allow its market data to be republished.
# Scheduling: see install_services.sh (systemd timer), or cron:
#   15 17 * * 1-5  /path/to/daily_sync.sh >> $HOME/pkmarket-sync.log 2>&1
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
