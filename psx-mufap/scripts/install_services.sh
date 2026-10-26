#!/usr/bin/env bash
# Install two systemd *user* services (no root needed):
#   pkm-daily.timer      runs daily_sync.sh on weekdays at 17:15 Pakistan time
#   pkm-dashboard        keeps the dashboard server running (127.0.0.1:8787 unless you set PKM_DASH_HOST)
#
#   PKM_HOME=~/pkmarket-data PKM_SCOPE=all ./install_services.sh
#   PKM_DASH_HOST=100.x.y.z PKM_DASHBOARD_PASSWORD='...' ./install_services.sh   # e.g. your Tailscale IP
#
# Remove with: systemctl --user disable --now pkm-daily.timer pkm-dashboard.service
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${PKM_HOME:=$HOME/pkmarket-data}"
: "${PKM_SCOPE:=watchlist}"
: "${PKM_DASH_HOST:=127.0.0.1}"
: "${PKM_DASH_PORT:=8787}"
UNIT_DIR="$HOME/.config/systemd/user"
ENV_FILE="$HOME/.config/pkm.env"
mkdir -p "$UNIT_DIR" "$PKM_HOME"
umask 077
{
  echo "PKM_HOME=$PKM_HOME"
  echo "PKM_SCOPE=$PKM_SCOPE"
  [ -n "${PKM_DASHBOARD_PASSWORD:-}" ] && echo "PKM_DASHBOARD_PASSWORD=$PKM_DASHBOARD_PASSWORD"
} > "$ENV_FILE"
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
Description=Run the PSX/MUFAP pipeline after the market closes

[Timer]
OnCalendar=Mon..Fri 17:15 Asia/Karachi
Persistent=true

[Install]
WantedBy=timers.target
UNIT

cat > "$UNIT_DIR/pkm-dashboard.service" <<UNIT
[Unit]
Description=PSX/MUFAP dashboard (read-only web server)
After=network-online.target

[Service]
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/env python3 $HERE/dashboard.py serve --host $PKM_DASH_HOST --port $PKM_DASH_PORT
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadOnlyPaths=$PKM_HOME

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now pkm-daily.timer pkm-dashboard.service
# Keep user services running when you are logged out (may ask for your password).
loginctl enable-linger "$USER" 2>/dev/null || echo "note: run 'sudo loginctl enable-linger $USER' to keep services running while logged out"
echo "installed. Next run: $(systemctl --user list-timers pkm-daily.timer --no-legend | awk '{print $1, $2, $3}')"
echo "dashboard: http://$PKM_DASH_HOST:$PKM_DASH_PORT/   logs: journalctl --user -u pkm-daily -u pkm-dashboard"
echo "first full run now (takes a while): systemctl --user start pkm-daily.service"
