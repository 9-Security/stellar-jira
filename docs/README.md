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

**Tier 3 飄移掃描（2026-07-27）— 相對於 `CURRENT_RUNTIME.md` + `DEMO_MVP_v0.1.md` + 程式碼：**

| 文件 | 狀態 | 主要飄移（勿當 runtime） |
|------|------|-------------------------|
| [`PRD_v0.1.md`](PRD_v0.1.md) | Draft 未實作 | 雙 Portal（SOC + Client）、`tenant_settings` DB 表、取代 Jira 為 Platform Ticket、Email 結案主通道 — **均未上線** |
| [`ACTUAL_ARCHITECTURE_FOR_SPEC.md`](ACTUAL_ARCHITECTURE_FOR_SPEC.md) | 2026-07-16 摘要 | 缺 `stellar-soc-api`、xMDR Web、`/v1/settings`、CyCraft inbound；僅列 automation service |
| [`Security_Decision_Platform_MVP_Spec_v1.0.md`](Security_Decision_Platform_MVP_Spec_v1.0.md) | v1.2 baseline | 同步/Jira/Decision 仍準；缺 xMDR、`platform.db` 整合器、`tenant_integrations`、CyCraft poller |
| [`README.md`](README.md) | 人類入門 | 已補 xMDR / `web/`；細節以 Tier 1 為準 |

**已上線 xMDR（老闆 Demo）** 見 [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md) v0.6，不是 PRD 雙 Portal。  
**CyCraft 營運 tenant：** `jjnet`（JJNET）。`env.example` 曾用 `jjnet-edr` 僅作 env suffix **範例**，不代表 CyCraft 綁在 JJNET-EDR。

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
| [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md) | **xMDR 老闆 Demo（已上線，v0.6 tenant 設定 / 外部整合器）** — 見文件 Tier 2 標記 |
| [`PRD_v0.1.md`](PRD_v0.1.md) | Future platform PRD — **AI: do not read by default** |
| [`Security_Decision_Platform_MVP_Spec_v1.0.md`](Security_Decision_Platform_MVP_Spec_v1.0.md) | Jira middleware spec — **AI: do not read by default** |

## Archive policy

Files in `docs/archive/` are frozen snapshots. They may contradict `CURRENT_RUNTIME.md`. Prefer **git history** over archive when reconstructing “why”.
