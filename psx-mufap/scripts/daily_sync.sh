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
: "${PKM_SCOPE:=watchlist}"
export PKM_SCOPE PKM_HOME PKM_GIT_PUSH 2>/dev/null || true
# The pipeline itself is daily.py (pure Python, so it also runs on Android and Windows).
exec python3 "$HERE/daily.py" --scope "$PKM_SCOPE" "$@"
