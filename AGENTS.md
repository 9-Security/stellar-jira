# AGENTS.md — guidance for AI coding agents

## Documentation (token discipline)

**Do not bulk-read `docs/`.** Use the tier list in [`docs/README.md`](docs/README.md).

### Read first (Tier 1)

1. [`docs/CURRENT_RUNTIME.md`](docs/CURRENT_RUNTIME.md) — Stellar↔Jira sync / automation
2. [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) — ops
3. [`env.example`](env.example) — env knobs
4. [`config/stellar_tenants.json`](config/stellar_tenants.json) when changing sync/report/tenant ops
5. Code under `app/stellar_sync/`, `app/stellar/`, `app/notify/` as needed

### Read when task-specific (Tier 2)

| Task area | Doc |
|-----------|-----|
| xMDR Web / login / dashboard / demo API | [`docs/DEMO_MVP_v0.1.md`](docs/DEMO_MVP_v0.1.md) + `app/platform/`, `app/demo/`, `web/` |
| Cloudflare Tunnel / public URL | [`docs/CLOUDFLARE_TUNNEL.md`](docs/CLOUDFLARE_TUNNEL.md) |
| Decision Layer | [`docs/DECISION_LAYER.md`](docs/DECISION_LAYER.md) |

### Do not read by default (Tier 3 — saves tokens)

| File | Reason |
|------|--------|
| [`docs/PRD_v0.1.md`](docs/PRD_v0.1.md) | Future product spec; shipped work is **DEMO_MVP** + sync runtime |
| [`docs/ACTUAL_ARCHITECTURE_FOR_SPEC.md`](docs/ACTUAL_ARCHITECTURE_FOR_SPEC.md) | External spec handoff; duplicate of runtime truth |
| [`docs/Security_Decision_Platform_MVP_Spec_v1.0.md`](docs/Security_Decision_Platform_MVP_Spec_v1.0.md) | Long spec; use `CURRENT_RUNTIME.md` instead |
| [`README.md`](README.md) | Human quick start; use this file + Tier 1 |
| **`docs/archive/**`** | Historical only |

Open Tier 3 / archive **only** when the user explicitly asks for PRD, spec rewrite, or history.

If a doc header contains `DO NOT READ`, `OUTDATED`, `HISTORICAL`, or `DO NOT USE FOR RUNTIME`, skip it.

### When docs conflict

Trust: **running `.env` + `docs/CURRENT_RUNTIME.md` + code** ≫ `docs/MAINTENANCE.md` ≫ `docs/DEMO_MVP_v0.1.md` (xMDR only) ≫ README ≫ Tier 3 ≫ archive.

## Product intent (short)

### Stellar↔Jira automation (production)

- Automation cycle: **inbound poll → mirror linked tickets → writeback**
- Multi-tenant: one global poll, strict registry classification, shared Jira project + `tenant-<source_id>` labels
- `cust_id` authoritative; unknown/mismatch/disabled → quarantine
- Create Jira for Critical/High only; status bidirectional; assignee Stellar→Jira only
- Email/LINE body matches Jira Description (`stellar_case_detail_lines`)
- Decision Layer may run; Decision text **not** appended to Jira Description by default
- MaiAgent full-case: optional fail-open **after Critical/High create only**; keep `MAIAGENT_ALL_CASES_ENABLED=false`

### xMDR Web (boss demo — read DEMO_MVP for detail)

- URL: https://xmdr.nine-security.com
- Read-only dashboard + cases over sync DB / Stellar live API
- `platform.db` for users; does **not** replace Jira automation

## Services

| Service | Role |
|---------|------|
| `ticket-api-stellar-jira.service` | Stellar↔Jira automation |
| `stellar-soc-api.service` | xMDR API + `web/dist` (`127.0.0.1:8000`) |
| `cloudflared-stellar-soc.service` | Tunnel to public URL |

Log: `/var/log/stellar_jira.log`  
After changing Python under `app/`: restart the relevant service (`MAINTENANCE.md`).
