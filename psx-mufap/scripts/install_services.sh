#!/usr/bin/env bash
# Install two systemd *user* services (no root needed):
#   pkm-daily.timer      runs daily_sync.sh at the times you choose (default 07:00, Mon-Fri)
#   pkm-dashboard        keeps the dashboard server running (127.0.0.1:8787 unless you set PKM_DASH_HOST)
#
#   ./install_services.sh                          watchlist, data in ~/pkmarket, 07:00 Mon-Fri
#   PKM_SCHEDULE="07:00,04:00" ./install_services.sh           run twice a day
#   PKM_SCHEDULE="18:30" PKM_DAYS="Mon..Sat" ./install_services.sh
#   PKM_DAYS="*" ./install_services.sh             every day of the week
#
# Times are Pakistan time (PKM_TZ, default Asia/Karachi), 24-hour HH:MM, comma-separated.
# PSX publishes the day's closing prices after about 15:30, so a morning run (e.g. 04:00 or
# 07:00) works from the previous session's close and is ready before the 09:30 open.
# Change the schedule any time by running this script again with new values.
#   PKM_SCOPE=all ./install_services.sh            every listed share
#   PKM_GIT_PUSH=1 PKM_HOME=~/my-private-data-repo ./install_services.sh   also push data (private repo only)
#   PKM_DASH_HOST=100.x.y.z PKM_DASHBOARD_PASSWORD='...' ./install_services.sh   # e.g. your Tailscale IP
#   PKM_DASH_REFRESH=0 ./install_services.sh       dashboard can't start a fetch (default: it can when
#                                                  it listens on 127.0.0.1 only; 1 to allow on other hosts)
#   PKM_DASH_LIVE=0 ./install_services.sh          no live prices on the dashboard (default: as PKM_DASH_REFRESH)
#
# Remove with: systemctl --user disable --now pkm-daily.timer pkm-dashboard.service
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${PKM_HOME:=$HOME/pkmarket}"
: "${PKM_GIT_PUSH:=0}"
: "${PKM_SCOPE:=watchlist}"
: "${PKM_DASH_HOST:=127.0.0.1}"
: "${PKM_DASH_PORT:=8787}"
# The page may ask for fresh data by default only when the server is on this computer alone.
case "$PKM_DASH_HOST" in 127.*|localhost|::1) : "${PKM_DASH_REFRESH:=1}" ;; *) : "${PKM_DASH_REFRESH:=0}" ;; esac
: "${PKM_DASH_LIVE:=$PKM_DASH_REFRESH}"   # live prices on the page: same default
: "${PKM_SCHEDULE:=07:00}"
: "${PKM_DAYS:=Mon..Fri}"
: "${PKM_TZ:=Asia/Karachi}"

# Validate the schedule before touching anything.
CALENDAR=""
IFS=',' read -r -a TIMES <<< "$PKM_SCHEDULE"
for t in "${TIMES[@]}"; do
  t="$(echo "$t" | tr -d ' ')"
  if ! [[ "$t" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    echo "PKM_SCHEDULE: '$t' is not a 24-hour HH:MM time (e.g. 07:00 or 04:00)" >&2; exit 2
  fi
  if [ "$PKM_DAYS" = "*" ]; then day=""; else day="$PKM_DAYS "; fi
  CALENDAR="${CALENDAR}OnCalendar=${day}*-*-* ${t}:00 ${PKM_TZ}"$'\n'
done
if [[ ! "$PKM_DAYS" =~ ^(\*|[A-Za-z.,]+)$ ]]; then
  echo "PKM_DAYS: use e.g. Mon..Fri, Mon,Wed,Fri, Mon..Sat or *" >&2; exit 2
fi
UNIT_DIR="$HOME/.config/systemd/user"
ENV_FILE="$HOME/.config/pkm.env"
mkdir -p "$UNIT_DIR" "$PKM_HOME"
umask 077
{
  echo "PKM_HOME=$PKM_HOME"
  echo "PKM_SCOPE=$PKM_SCOPE"
  echo "PKM_GIT_PUSH=$PKM_GIT_PUSH"
  [ -n "${PKM_DASHBOARD_PASSWORD:-}" ] && echo "PKM_DASHBOARD_PASSWORD=$PKM_DASHBOARD_PASSWORD"
  [ -n "${PKM_DASH_HOSTNAMES:-}" ] && echo "PKM_DASH_HOSTNAMES=$PKM_DASH_HOSTNAMES"
} > "$ENV_FILE"
# With PKM_DASH_REFRESH=1 the dashboard page may start a fetch, so the server needs to write the data folder.
DASH_FLAGS=""
[ "$PKM_DASH_REFRESH" = "1" ] && DASH_FLAGS="--allow-refresh"
[ "$PKM_DASH_LIVE" = "1" ] && DASH_FLAGS="$DASH_FLAGS --allow-live"
if [ -n "$DASH_FLAGS" ]; then
  DASH_PATHS="ReadWritePaths=$PKM_HOME"; DASH_DESC="web server that may fetch on request"
else
  DASH_PATHS="ReadOnlyPaths=$PKM_HOME"; DASH_DESC="read-only web server"
fi
chmod 600 "$ENV_FILE"

cat > "$UNIT_DIR/pkm-daily.service" <<UNIT
[Unit]
Description=PSX/MUFAP daily data, paper account and dashboard refresh
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=$ENV_FILE
ExecStart=$HERE/daily_sync.sh
Nice=10
UNIT

cat > "$UNIT_DIR/pkm-daily.timer" <<UNIT
[Unit]
Description=Run the PSX/MUFAP pipeline ($PKM_SCHEDULE, $PKM_DAYS, $PKM_TZ)

[Timer]
${CALENDAR}Persistent=true

[Install]
WantedBy=timers.target
UNIT

cat > "$UNIT_DIR/pkm-dashboard.service" <<UNIT
[Unit]
Description=PSX/MUFAP dashboard ($DASH_DESC)
After=network-online.target

[Service]
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/env python3 $HERE/dashboard.py serve --host $PKM_DASH_HOST --port $PKM_DASH_PORT $DASH_FLAGS
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
$DASH_PATHS

[Install]
WantedBy=default.target
UNIT

if command -v systemd-analyze >/dev/null; then  # check every calendar expression parses
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if ! systemd-analyze calendar "${line#OnCalendar=}" >/dev/null 2>&1; then
      echo "systemd rejects the schedule: $line" >&2; exit 2
    fi
  done <<< "$CALENDAR"
fi
systemctl --user daemon-reload
systemctl --user enable --now pkm-daily.timer pkm-dashboard.service
# Keep user services running when you are logged out (may ask for your password).
loginctl enable-linger "$USER" 2>/dev/null || echo "note: run 'sudo loginctl enable-linger $USER' to keep services running while logged out"
echo "installed: runs at $PKM_SCHEDULE ($PKM_DAYS, $PKM_TZ)."
echo "next run: $(systemctl --user list-timers pkm-daily.timer --no-legend | awk '{print $1, $2, $3}')"
echo "dashboard: http://$PKM_DASH_HOST:$PKM_DASH_PORT/   logs: journalctl --user -u pkm-daily -u pkm-dashboard"
echo "first full run now (takes a while): systemctl --user start pkm-daily.service"
