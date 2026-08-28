#!/usr/bin/env bash
# Cloud Agent environment bootstrap for stellar-jira (xMDR / AIxSOC).
# Idempotent: safe to re-run. Prepares Python venv, builds the web UI, and
# seeds a dev-only .env so the local HTTP API + SPA can run immediately.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 1) System dependency required to create Python virtualenvs (ensurepip).
if ! python3 -m ensurepip --version >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3.12-venv python3-pip
fi

# 2) Python venv + backend dependencies.
bash Tools/setup_env.sh

# 3) Web frontend build -> web/dist (served by the API at /).
if [ -d web ]; then
  ( cd web && npm ci && npm run build )
fi

# 4) Dev-only .env (never committed). Real STELLAR_*/JIRA_* credentials go here
#    later; placeholders keep the local API + UI runnable for the demo.
if [ ! -f .env ]; then
  cp env.example .env
  SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  sed -i "s|^STELLAR_TENANT_ID=.*|STELLAR_TENANT_ID=dev-tenant-0000|" .env
  sed -i "s|^STELLAR_BASE_URL=.*|STELLAR_BASE_URL=https://stellar.local.invalid|" .env
  sed -i "s|^STELLAR_API_KEY=.*|STELLAR_API_KEY=dev-placeholder-key|" .env
  sed -i "s|^PLATFORM_SECRET_KEY=.*|PLATFORM_SECRET_KEY=${SECRET}|" .env
fi

echo "[install] stellar-jira environment ready"
