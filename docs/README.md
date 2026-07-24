> **AI AGENTS:** Doc routing table — [`../AGENTS.md`](../AGENTS.md). Do not load every linked file.

# Documentation index

> **AI agents:** Start at repo root [`AGENTS.md`](../AGENTS.md). This page is the **routing table** — do not load every file listed below.

## Tier 1 — Read first (runtime truth)

| File | When |
|------|------|
| [`../AGENTS.md`](../AGENTS.md) | Always — reading policy + product one-liner |
| [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md) | Stellar↔Jira sync, poll, writeback, notify, multi-tenant |
| [`MAINTENANCE.md`](MAINTENANCE.md) | systemd, CLI, logs, reports, xMDR restart |
| [`../env.example`](../env.example) | Env knobs (never commit `.env`) |
| [`../config/stellar_tenants.json`](../config/stellar_tenants.json) | Tenant registry (when changing sync/report/tenant) |

**Conflict order:** `.env` + `CURRENT_RUNTIME.md` + code ≫ `MAINTENANCE.md` ≫ everything else.

## Tier 2 — Read when the task needs it

| File | When |
|------|------|
| [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md) | xMDR Web UI, `app/platform/`, `app/demo/`, `web/`, boss demo |
| [`PRODUCTION_DEPLOY_ONPREM.md`](PRODUCTION_DEPLOY_ONPREM.md) | Git clone、地端 VM、`/var/lib/xmdr` 資料分離 |
| [`CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md) | Tunnel, `xmdr.nine-security.com`, `cloudflared`, public URL |
| [`DECISION_LAYER.md`](DECISION_LAYER.md) | Decision rules, dataset, outcome, `app/decision/` |

## Tier 3 — Do not read by default (token waste)

| File | Why skip | Read only if |
|------|----------|--------------|
| [`PRD_v0.1.md`](PRD_v0.1.md) | **~700 lines** future dual-portal product spec; most **not implemented** | User asks for full PRD / long-term product design |
| [`ACTUAL_ARCHITECTURE_FOR_SPEC.md`](ACTUAL_ARCHITECTURE_FOR_SPEC.md) | ChatGPT handoff paste; **duplicates** `CURRENT_RUNTIME.md` | User asks to rewrite external spec / paste to another model |
| [`Security_Decision_Platform_MVP_Spec_v1.0.md`](Security_Decision_Platform_MVP_Spec_v1.0.md) | Long product baseline; **overlaps** runtime docs | User asks for complete product spec document |
| [`../README.md`](../README.md) | Human onboarding; overlaps Tier 1 | User asks for quick start only |

## Tier 4 — Archive (never read unless asked)

| Path | Status |
|------|--------|
| [`archive/`](archive/) | **OUTDATED / HISTORICAL — DO NOT USE FOR RUNTIME** |
| [`archive/PENDING_IMPROVEMENTS.md`](archive/PENDING_IMPROVEMENTS.md) | Completed backlog |
| [`archive/AI_Security_Decision_Platform_Notes.md`](archive/AI_Security_Decision_Platform_Notes.md) | Strategy brainstorm |

See [`archive/README.md`](archive/README.md).

## For humans

| Doc | Purpose |
|-----|---------|
| [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md) | **xMDR 老闆 Demo（已上線）** — 見文件 Tier 2 標記 |
| [`PRD_v0.1.md`](PRD_v0.1.md) | Future platform PRD — **AI: do not read by default** |
| [`Security_Decision_Platform_MVP_Spec_v1.0.md`](Security_Decision_Platform_MVP_Spec_v1.0.md) | Jira middleware spec — **AI: do not read by default** |

## Archive policy

Files in `docs/archive/` are frozen snapshots. They may contradict `CURRENT_RUNTIME.md`. Prefer **git history** over archive when reconstructing “why”.
