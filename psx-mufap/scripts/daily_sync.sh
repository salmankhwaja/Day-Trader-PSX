#!/usr/bin/env bash
# Daily data refresh for a computer with normal internet (e.g. Linux Mint), so Claude on
# your phone can use fresh PSX prices even where its sandbox can't reach the PSX site.
#
#   PKM_HOME=~/pkmarket-data ./daily_sync.sh
#
# If PKM_HOME is a git repo, new data is committed and pushed. MAKE THAT REPO PRIVATE:
# PSX does not allow its market data to be republished.
#
# Weekdays at 17:15 Pakistan time, via `crontab -e` (cron uses the computer's local time):
#   15 17 * * 1-5  PKM_HOME=$HOME/pkmarket-data /path/to/psx-mufap/scripts/daily_sync.sh >> $HOME/pkmarket-sync.log 2>&1
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${PKM_HOME:=$HOME/pkmarket-data}"
export PKM_HOME
mkdir -p "$PKM_HOME"
echo "== $(date '+%F %T') sync into $PKM_HOME"
python3 "$HERE/pkdata.py" psx --watchlist || echo "some PSX symbols failed"
python3 "$HERE/pkdata.py" mufap || echo "MUFAP failed"
if [ -d "$PKM_HOME/.git" ]; then
  cd "$PKM_HOME"
  git add -A
  if ! git diff --cached --quiet; then
    git commit -q -m "data: $(date +%F)" && git push -q && echo "pushed"
  else
    echo "no changes"
  fi
fi
