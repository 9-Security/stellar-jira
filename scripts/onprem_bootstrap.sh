#!/usr/bin/env bash
# Bootstrap on-prem: venv, web build, /var/lib/xmdr data link, systemd.
# Run from repo root after git clone. Requires root for systemd install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_USER="${APP_USER:-$(logname 2>/dev/null || echo root)}"
DATA_DIR="${DATA_DIR:-/var/lib/xmdr}"
ENV_FILE="${ENV_FILE:-/etc/xmdr/.env}"

echo "[onprem] repo=$ROOT data=$DATA_DIR env=$ENV_FILE user=$APP_USER"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[onprem] Re-run with sudo: sudo $0" >&2
  exit 1
fi

mkdir -p "$DATA_DIR" "$(dirname "$ENV_FILE")"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR" "$ROOT" 2>/dev/null || true

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ROOT/env.example" ]]; then
    cp "$ROOT/env.example" "$ENV_FILE"
    chmod 640 "$ENV_FILE"
    echo "[onprem] Created $ENV_FILE from env.example — edit before production."
  else
    echo "[onprem] WARN: no $ENV_FILE; create from env.example" >&2
  fi
fi

# data/ → /var/lib/xmdr
if [[ -L "$ROOT/data" ]]; then
  :
elif [[ -d "$ROOT/data" ]] && [[ "$(ls -A "$ROOT/data" 2>/dev/null | head -1)" != "" ]]; then
  echo "[onprem] Moving existing data/* to $DATA_DIR ..."
  shopt -s dotglob nullglob
  for item in "$ROOT/data"/*; do
    base="$(basename "$item")"
    [[ "$base" == ".gitkeep" ]] && continue
    if [[ ! -e "$DATA_DIR/$base" ]]; then
      mv "$item" "$DATA_DIR/"
    fi
  done
  rmdir "$ROOT/data" 2>/dev/null || rm -rf "$ROOT/data"
  ln -sfn "$DATA_DIR" "$ROOT/data"
else
  rm -rf "$ROOT/data"
  ln -sfn "$DATA_DIR" "$ROOT/data"
  touch "$DATA_DIR/.gitkeep"
fi
chown -h "$APP_USER:$APP_USER" "$ROOT/data" 2>/dev/null || true
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"

echo "[onprem] Python venv + requirements ..."
sudo -u "$APP_USER" bash "$ROOT/Tools/setup_env.sh"

if command -v npm >/dev/null 2>&1; then
  echo "[onprem] web-build ..."
  sudo -u "$APP_USER" bash "$ROOT/Tools/run" web-build
else
  echo "[onprem] WARN: npm not found — install Node.js then: ./Tools/run web-build" >&2
fi

install_unit() {
  local unit="$1"
  install -m 644 "$ROOT/deploy/systemd/$unit" "/etc/systemd/system/$unit"
}

install_unit ticket-api-stellar-jira.service
install_unit stellar-soc-api.service
install_unit ticket-api-stellar-jira-watchdog.service
install_unit ticket-api-stellar-jira-watchdog.timer

if [[ -f "$ROOT/deploy/systemd/cloudflared-stellar-soc.service" ]]; then
  install_unit cloudflared-stellar-soc.service
fi

systemctl daemon-reload
systemctl enable ticket-api-stellar-jira.service stellar-soc-api.service
systemctl enable ticket-api-stellar-jira-watchdog.timer 2>/dev/null || true

echo "[onprem] Done. Next:"
echo "  1. Edit $ENV_FILE (Stellar, Jira, PLATFORM_SECRET_KEY)"
echo "  2. Copy /var/lib/xmdr from old server if migrating"
echo "  3. sudo systemctl start ticket-api-stellar-jira stellar-soc-api"
echo "  4. ./Tools/run platform-user create ...  (if no platform.db)"
echo "  5. curl -s http://127.0.0.1:8000/health"
