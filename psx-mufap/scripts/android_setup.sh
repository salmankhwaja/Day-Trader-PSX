#!/data/data/com.termux/files/usr/bin/bash
# One-time setup on an Android phone, inside Termux. Safe to run again (e.g. to change the times).
#
#   bash ~/Day-Trader-PSX/psx-mufap/scripts/android_setup.sh
#   PKM_SCHEDULE="07:00,04:00" PKM_DAYS="Mon..Fri" bash .../android_setup.sh
#   PKM_SCOPE=all bash .../android_setup.sh          # whole market every day
#
# It:
#   1. installs what's needed (cronie and termux-services for timers; python and git you have)
#   2. checks access to Internal storage (your data lives in Internal storage/pkmarket)
#   3. creates config.json if missing
#   4. schedules the daily update with cron at PKM_SCHEDULE (phone's time zone)
#   5. runs the dashboard as a background service at http://127.0.0.1:8787 (this phone only)
#   6. adds Termux:Widget shortcuts (PSX-menu, PSX-update, PSX-dashboard)
#   7. adds a Termux:Boot script so the timer and dashboard come back after a restart
set -eu
: "${PREFIX:=/data/data/com.termux/files/usr}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python || command -v python3)"
: "${PKM_SCHEDULE:=07:00}"
: "${PKM_DAYS:=Mon..Fri}"
: "${PKM_SCOPE:=watchlist}"
: "${PKM_DASH_REFRESH:=1}"   # 0 = the dashboard page can't start a fetch
: "${PKM_DASH_LIVE:=1}"      # 0 = no live prices on the dashboard
DATA=/storage/emulated/0/pkmarket

say() { printf '\n== %s\n' "$*"; }

say "1/7 packages"
pkg install -y python git cronie termux-services >/dev/null || { echo "pkg install failed: run 'pkg update' and try again"; exit 1; }
PY="$(command -v python)"

say "2/7 storage"
if [ ! -w /storage/emulated/0 ]; then
  echo "Termux can't write to Internal storage yet. Run: termux-setup-storage"
  echo "tap Allow, then run this script again."
  exit 1
fi
mkdir -p "$DATA"
echo "data folder: $DATA"

say "3/7 config"
export PKM_HOME="$DATA"
"$PY" "$HERE/pkdata.py" init

say "4/7 schedule ($PKM_SCHEDULE, $PKM_DAYS)"
case "$PKM_DAYS" in
  "*") DOW="*" ;;
  Mon..Fri) DOW="1-5" ;;
  Mon..Sat) DOW="1-6" ;;
  Sun..Sat|Mon..Sun) DOW="*" ;;
  *) DOW="$(echo "$PKM_DAYS" | sed 's/Sun/0/g;s/Mon/1/g;s/Tue/2/g;s/Wed/3/g;s/Thu/4/g;s/Fri/5/g;s/Sat/6/g;s/\.\./-/g')" ;;
esac
if ! echo "$DOW" | grep -Eq '^(\*|[0-6]([-,][0-6])*)$'; then
  echo "PKM_DAYS: use Mon..Fri, Mon..Sat, Mon,Wed,Fri or *"; exit 2
fi
LINES=""
IFS=',' read -r -a TIMES <<< "$PKM_SCHEDULE"
for t in "${TIMES[@]}"; do
  t="$(echo "$t" | tr -d ' ')"
  if ! [[ "$t" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]]; then
    echo "PKM_SCHEDULE: '$t' is not a 24-hour HH:MM time"; exit 2
  fi
  LINES="${LINES}$((10#${BASH_REMATCH[2]})) $((10#${BASH_REMATCH[1]})) * * $DOW PKM_HOME=$DATA PKM_SCOPE=$PKM_SCOPE $PY $HERE/daily.py --log $DATA/daily.log # pkm-daily"$'\n'
done
{ crontab -l 2>/dev/null | grep -v '# pkm-daily' || true; printf '%s' "$LINES"; } | crontab -
crontab -l | grep 'pkm-daily'
echo "times are in the phone's time zone ($(date +%Z))"

say "5/7 dashboard service"
SV="$PREFIX/var/service/pkm-dashboard"
mkdir -p "$SV"
cat > "$SV/run" <<EOF
#!$PREFIX/bin/sh
export PKM_HOME=$DATA PKM_SCOPE=$PKM_SCOPE
exec $PY $HERE/dashboard.py serve --host 127.0.0.1 --port 8787 $( [ "$PKM_DASH_REFRESH" = "1" ] && echo --allow-refresh ) $( [ "$PKM_DASH_LIVE" = "1" ] && echo --allow-live ) 2>&1
EOF
chmod +x "$SV/run"
# Build once so the page has something to show before the first scheduled run.
"$PY" "$HERE/dashboard.py" build >/dev/null 2>&1 || true
if sv-enable crond 2>/dev/null && sv-enable pkm-dashboard 2>/dev/null; then
  echo "running: cron timer and dashboard (http://127.0.0.1:8787)"
else
  echo "termux-services needs Termux restarted once: type 'exit', open Termux again,"
  echo "and run this script again (it is safe to repeat)."
fi

say "6/7 home-screen shortcuts (needs the Termux:Widget app)"
mkdir -p "$HOME/.shortcuts"
printf '#!%s/bin/sh\nexport PKM_HOME=%s\ncd %s && %s pkm.py\n' "$PREFIX" "$DATA" "$HERE" "$PY" > "$HOME/.shortcuts/PSX-menu"
printf '#!%s/bin/sh\nexport PKM_HOME=%s PKM_SCOPE=%s\n%s %s/daily.py --log %s/daily.log\necho; echo "done: open http://127.0.0.1:8787"; sleep 5\n' \
  "$PREFIX" "$DATA" "$PKM_SCOPE" "$PY" "$HERE" "$DATA" > "$HOME/.shortcuts/PSX-update"
printf '#!%s/bin/sh\ntermux-open-url http://127.0.0.1:8787\n' "$PREFIX" > "$HOME/.shortcuts/PSX-dashboard"
chmod +x "$HOME/.shortcuts/"PSX-*
echo "PSX-menu, PSX-update, PSX-dashboard"

say "7/7 start after a phone restart (needs the Termux:Boot app, opened once)"
mkdir -p "$HOME/.termux/boot"
printf '#!%s/bin/sh\ntermux-wake-lock\n. %s/etc/profile\n' "$PREFIX" "$PREFIX" > "$HOME/.termux/boot/start-pkm"
chmod +x "$HOME/.termux/boot/start-pkm"
termux-wake-lock 2>/dev/null || true

say "done"
cat <<EOF
Next:
  - Fetch your first data now:   PKM_HOME=$DATA $PY $HERE/daily.py
  - Open the dashboard in Chrome: http://127.0.0.1:8787  (Chrome menu > Add to Home screen)
  - The menu for everything else: cd $HERE && $PY pkm.py
  - Settings > Apps > Termux > Battery > Unrestricted, so the timer fires on time.
EOF
