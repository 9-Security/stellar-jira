#!/usr/bin/env bash
# systemd oneshot: ensure Stellar→Jira automation is running; restart if log is stale (hung).
set -euo pipefail

ROOT="${STELLAR_JIRA_ROOT:-/opt/stellar-jira}"
MAIN_UNIT="${STELLAR_JIRA_AUTOMATION_UNIT:-ticket-api-stellar-jira.service}"
LOG="${STELLAR_JIRA_AUTOMATION_LOG:-/var/log/stellar_jira.log}"
STALE="${STELLAR_JIRA_AUTOMATION_STALE_SEC:-300}"

log_msg() {
  echo "[stellar-watchdog] $*" >&2
  command -v logger >/dev/null 2>&1 && logger -t stellar-jira-watchdog "$*" || true
}

active=$(systemctl is-active "$MAIN_UNIT" 2>/dev/null || echo "inactive")
if [[ "$active" != "active" ]]; then
  log_msg "unit $MAIN_UNIT is $active → start"
  systemctl start "$MAIN_UNIT" || log_msg "start failed (exit $?)"
  exit 0
fi

if [[ ! -f "$LOG" ]]; then
  log_msg "missing $LOG → restart $MAIN_UNIT"
  systemctl restart "$MAIN_UNIT" || true
  exit 0
fi

now=$(date +%s)
mtime=$(stat -c %Y "$LOG" 2>/dev/null || echo 0)
age=$((now - mtime))
if [[ "$age" -gt "$STALE" ]]; then
  log_msg "log stale ${age}s (threshold ${STALE}s) → restart $MAIN_UNIT"
  systemctl restart "$MAIN_UNIT" || true
fi
