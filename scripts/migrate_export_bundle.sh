#!/usr/bin/env bash
# Export stellar-jira state from current host (e.g. GCP test VM) for on-prem migration.
# Run on SOURCE host. Output: /tmp/stellar-jira-migrate-YYYYMMDD-HHMMSS.tar.gz
#
# Usage:
#   sudo ./scripts/migrate_export_bundle.sh
#   sudo ./scripts/migrate_export_bundle.sh --no-stop   # skip stopping services (not recommended)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NO_STOP=false
for arg in "$@"; do
  case "$arg" in
    --no-stop) NO_STOP=true ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$(mktemp -d /tmp/stellar-jira-migrate-build.XXXXXX)"
BUNDLE_DIR="$OUT_DIR/stellar-jira-migrate"
ARCHIVE="/tmp/stellar-jira-migrate-${STAMP}.tar.gz"

mkdir -p "$BUNDLE_DIR/meta" "$BUNDLE_DIR/restore"

echo "[migrate-export] repo: $ROOT"
echo "[migrate-export] bundle: $ARCHIVE"

if [[ "$NO_STOP" == false ]]; then
  echo "[migrate-export] stopping services (if running)..."
  for svc in cloudflared-stellar-soc.service stellar-soc-api.service \
    ticket-api-stellar-jira.service cycraft-xcockpit-connector.service \
    cycraft-stellar-xdr.service; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
      systemctl stop "$svc" || true
      echo "  stopped $svc"
    fi
  done
  sleep 2
fi

# Metadata for target host
{
  echo "exported_at=$(date -Is)"
  echo "hostname=$(hostname -f 2>/dev/null || hostname)"
  echo "git_rev=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_branch=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  uname -a
} >"$BUNDLE_DIR/meta/source_host.txt"

# Secrets + runtime config (never commit to git)
if [[ -f "$ROOT/.env" ]]; then
  install -m 600 "$ROOT/.env" "$BUNDLE_DIR/restore/.env"
else
  echo "[migrate-export] WARN: no .env" >&2
fi

if [[ -f /etc/xmdr/.env ]]; then
  install -m 600 /etc/xmdr/.env "$BUNDLE_DIR/restore/xmdr.env"
fi

# Data + configs
mkdir -p "$BUNDLE_DIR/restore/data" "$BUNDLE_DIR/restore/config"

for f in platform.db stellar_sync_state.sqlite; do
  if [[ -f "$ROOT/data/$f" ]]; then
    cp -a "$ROOT/data/$f" "$BUNDLE_DIR/restore/data/"
  fi
done

if [[ -d "$ROOT/data/case_archive" ]]; then
  cp -a "$ROOT/data/case_archive" "$BUNDLE_DIR/restore/data/"
fi

for cfg in stellar_tenants.json stellar_jira_field_map.json stellar_jira_user_map.json \
  stellar_jira_workflow_status_map.json stellar_resolution_tag_map.json; do
  if [[ -f "$ROOT/config/$cfg" ]]; then
    cp -a "$ROOT/config/$cfg" "$BUNDLE_DIR/restore/config/"
  fi
done

# Cloudflare tunnel token (move connector to new VM)
if [[ -f "$ROOT/.cloudflare/tunnel.token" ]]; then
  mkdir -p "$BUNDLE_DIR/restore/.cloudflare"
  install -m 600 "$ROOT/.cloudflare/tunnel.token" "$BUNDLE_DIR/restore/.cloudflare/tunnel.token"
fi

# Pre-built UI (optional — can web-build on target instead)
if [[ -d "$ROOT/web/dist" ]]; then
  mkdir -p "$BUNDLE_DIR/restore/web"
  cp -a "$ROOT/web/dist" "$BUNDLE_DIR/restore/web/dist"
fi

cat >"$BUNDLE_DIR/RESTORE_README.txt" <<'EOF'
stellar-jira migration bundle

On the ON-PREM target VM:
  1. git clone git@github.com:9-Security/stellar-jira.git /opt/stellar-jira
  2. Extract this archive and run:
       sudo ./scripts/migrate_onprem_install.sh /path/to/stellar-jira-migrate-*.tar.gz
  3. Follow docs/ONPREM_MIGRATION.md for Cloudflare / firewall / verification.

Do not store this archive in git or public object storage without encryption.
EOF

tar -czf "$ARCHIVE" -C "$OUT_DIR" stellar-jira-migrate
rm -rf "$OUT_DIR"

echo "[migrate-export] OK: $ARCHIVE"
du -sh "$ARCHIVE"
echo "[migrate-export] Transfer securely to on-prem (scp/rsync), then decommission GCP after cutover."
