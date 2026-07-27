#!/usr/bin/env bash
# Restore stellar-jira migration bundle on on-prem VM and install systemd units.
#
# Usage:
#   sudo ./scripts/migrate_onprem_install.sh /tmp/stellar-jira-migrate-YYYYMMDD-HHMMSS.tar.gz
#   sudo ./scripts/migrate_onprem_install.sh /path/to/bundle.tar.gz --skip-services

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ARCHIVE=""
SKIP_SERVICES=false
for arg in "$@"; do
  case "$arg" in
    --skip-services) SKIP_SERVICES=true ;;
    -h|--help)
      sed -n '1,8p' "$0"
      exit 0
      ;;
    *)
      if [[ -z "$ARCHIVE" ]]; then
        ARCHIVE="$arg"
      else
        echo "Unknown argument: $arg" >&2
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "Usage: sudo $0 /path/to/stellar-jira-migrate-*.tar.gz" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

WORK="$(mktemp -d /tmp/stellar-jira-restore.XXXXXX)"
tar -xzf "$ARCHIVE" -C "$WORK"
SRC="$WORK/stellar-jira-migrate/restore"
if [[ ! -d "$SRC" ]]; then
  echo "Invalid bundle layout (missing stellar-jira-migrate/restore)" >&2
  exit 1
fi

echo "[migrate-install] target repo: $ROOT"

if [[ -f "$SRC/.env" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    cp -a "$ROOT/.env" "$ROOT/.env.bak.$(date +%Y%m%d%H%M%S)"
  fi
  install -m 600 "$SRC/.env" "$ROOT/.env"
  echo "[migrate-install] restored .env"
fi

if [[ -f "$SRC/xmdr.env" ]]; then
  mkdir -p /etc/xmdr
  install -m 600 "$SRC/xmdr.env" /etc/xmdr/.env
  echo "[migrate-install] restored /etc/xmdr/.env"
fi

mkdir -p "$ROOT/data" "$ROOT/config"
if [[ -d "$SRC/data" ]]; then
  cp -a "$SRC/data/." "$ROOT/data/"
  echo "[migrate-install] restored data/"
fi
if [[ -d "$SRC/config" ]]; then
  for f in "$SRC/config"/*; do
    [[ -f "$f" ]] || continue
    install -m 644 "$f" "$ROOT/config/$(basename "$f")"
  done
  echo "[migrate-install] restored config overrides"
fi

if [[ -f "$SRC/.cloudflare/tunnel.token" ]]; then
  mkdir -p "$ROOT/.cloudflare"
  install -m 600 "$SRC/.cloudflare/tunnel.token" "$ROOT/.cloudflare/tunnel.token"
  echo "[migrate-install] restored Cloudflare tunnel token"
fi

if [[ -d "$SRC/web/dist" ]]; then
  mkdir -p "$ROOT/web"
  rm -rf "$ROOT/web/dist"
  cp -a "$SRC/web/dist" "$ROOT/web/dist"
  echo "[migrate-install] restored web/dist"
fi

echo "[migrate-install] Python venv..."
if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
  bash "$ROOT/Tools/setup_env.sh"
else
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
fi

echo "[migrate-install] systemd units..."
install -m 644 "$ROOT/deploy/systemd/stellar-soc-api.service" /etc/systemd/system/
install -m 644 "$ROOT/deploy/systemd/ticket-api-stellar-jira.service" /etc/systemd/system/
install -m 644 "$ROOT/deploy/systemd/ticket-api-stellar-jira-watchdog.service" /etc/systemd/system/ 2>/dev/null || true
install -m 644 "$ROOT/deploy/systemd/ticket-api-stellar-jira-watchdog.timer" /etc/systemd/system/ 2>/dev/null || true

if [[ -f "$ROOT/.cloudflare/tunnel.token" ]]; then
  install -m 644 "$ROOT/deploy/systemd/cloudflared-stellar-soc-token.service" /etc/systemd/system/cloudflared-stellar-soc.service
  sed -i "s|CLOUDFLARE_TUNNEL_TOKEN_FILE_PLACEHOLDER|$ROOT/.cloudflare/tunnel.token|g" \
    /etc/systemd/system/cloudflared-stellar-soc.service
fi

chmod +x "$ROOT/scripts/systemd_watchdog_stellar_automation.sh" 2>/dev/null || true

systemctl daemon-reload

if [[ "$SKIP_SERVICES" == false ]]; then
  systemctl enable stellar-soc-api.service ticket-api-stellar-jira.service
  systemctl restart stellar-soc-api.service
  systemctl restart ticket-api-stellar-jira.service
  if [[ -f /etc/systemd/system/cloudflared-stellar-soc.service ]]; then
    systemctl enable cloudflared-stellar-soc.service
    systemctl restart cloudflared-stellar-soc.service
  fi
  systemctl enable ticket-api-stellar-jira-watchdog.timer 2>/dev/null || true
  systemctl start ticket-api-stellar-jira-watchdog.timer 2>/dev/null || true
fi

rm -rf "$WORK"

echo "[migrate-install] Verification:"
curl -sf "http://127.0.0.1:8000/health" && echo "" || echo "WARN: stellar-soc-api not responding on :8000"
systemctl is-active stellar-soc-api.service ticket-api-stellar-jira.service 2>/dev/null || true
echo "[migrate-install] Done. See docs/ONPREM_MIGRATION.md for cutover checklist."
