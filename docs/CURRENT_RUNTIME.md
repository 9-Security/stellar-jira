> **AI AGENTS — AUTHORITATIVE (Tier 1).** Read for Stellar↔Jira sync, poll, writeback, notify, multi-tenant.  
> Do **not** infer runtime from `docs/archive/`, `PRD_v0.1.md`, or long product specs.

# Current runtime (source of truth)

> **For humans and AI agents:** This is the authoritative description of how
> `stellar-jira` runs in production as of **2026-07-16**.
> Do **not** infer sync behavior from files under `docs/archive/` or other
> historical notes.

Service: `ticket-api-stellar-jira.service`  
Log: `/var/log/stellar_jira.log`  
State DB: `data/stellar_sync_state.sqlite`

## Cycle model

Each automation cycle:

```text
inbound poll (modified cases in lookback)
  → strict tenant registry classification by cust_id + tenant_name
  → create Jira for new Critical/High cases (Decision Layer may defer/suppress)
  → for already-linked cases: mirror Status / Assignee / Case Activity → Jira
writeback (linked Jira issues whose Jira ``updated`` changed)
  → Status (+ optional resolution tag) → Stellar
sleep STELLAR_AUTOMATION_INTERVAL_SECONDS (often 5s; idle writeback is cheap)
```

- **Poll mirror on:** `STELLAR_MIRROR_ON_POLL=true`
- **Full mirror scan off:** `STELLAR_MIRROR_FULL_SCAN=false` (do not re-enable unless debugging)
- Full-scan mirror remains legacy single-scope code; keep it off in multi-tenant production.
- Linked cases are processed **before** deferred create retries
- **Writeback incremental:** cycle prefetches Jira `updated` via JQL; tickets unchanged since last check are skipped (no Stellar GET)

### Multi-tenant ownership

- `STELLAR_MULTI_TENANT_ENABLED=true` performs one global cases poll; it does not run one poll per tenant.
- `config/stellar_tenants.json` is the tenant registry. `cust_id` is authoritative and
  `tenant_name` is cross-checked. Unknown IDs, name mismatches, and disabled tenants are
  persisted in `tenant_case_quarantine`; they cannot create Jira issues.
- Quarantine reasons are `unknown_tenant_id`, `tenant_name_mismatch`,
  `missing_or_unknown_tenant`, and `tenant_disabled`. Each cycle re-injects rows
  that now resolve to an enabled tenant; successful handling clears the row.
- Registry flags: `enabled` is the master switch, `sync_enabled` controls inbound
  sync, and `reporting_enabled` controls report selection. Tenant enable/disable
  commands currently toggle all three together.
- In global mode `STELLAR_TENANT_ID` is not sent to Cases API. It may still supply
  an env-expanded registry value such as `"tenant_id": "${STELLAR_TENANT_ID}"`.
- All tenants use the shared Jira project unless a registry entry explicitly overrides it.
  Issues include `tenant-<source_id>` plus configured labels, and Description includes
  Tenant / Tenant ID for filtering and audit.
- Monthly-report Jira MTTR uses the same `tenant-<source_id>` label, so statistics remain
  tenant-scoped even when all issues share `AIXSOC`.
- The existing global `source_id=stellar` mapping and watermark are retained to prevent
  duplicate tickets. Tenant ownership is additional metadata on each mapping.
- Registry operations: `tenant-list`, `tenant-discover`, `tenant-validate`,
  `tenant-enable`, `tenant-disable`, `tenant-health`, `tenant-quarantine`, and
  `tenant-backfill`.
- Current registry has two enabled tenants: `jjnet` (`JJNET`, customer code
  `JJNET`) and `jjnet-edr` (`JJNET-EDR`, customer code `JJEDR`). Both share
  Jira project `AIXSOC`; product availability remains tenant-specific.
- `tenant-backfill` migrates SQLite link ownership only. It does not edit existing
  Jira issues. Historical MTTR requires those older issues to already have the
  `tenant-<source_id>` label; all newly created issues receive it automatically.

## Field sync matrix

| Field | Stellar → Jira | Jira → Stellar |
|-------|----------------|----------------|
| Status (Workflow + 事件狀態 `customfield_10061`) | yes | yes |
| Assignee | yes (email → accountId via user map) | **no** |
| Severity | on create | **no** |
| Case Activity → Jira comment | yes (deduped) | — |
| Jira comment → Stellar | — | **webhook only** (`commentId` / text) |
| New ticket create | Critical/High only | — |

Key env (duty / one-place ops):

```env
STELLAR_JIRA_MASTER_AFTER_LINK=false
STELLAR_AUTOMATION_JIRA_MIRROR=true
STELLAR_MIRROR_ON_POLL=true
STELLAR_MIRROR_FULL_SCAN=false
STELLAR_SYNC_STELLAR_TO_JIRA_STATUS=true
STELLAR_SYNC_STELLAR_TO_JIRA_ASSIGNEE=true
STELLAR_WRITEBACK_SYNC_STATUS=true
STELLAR_WRITEBACK_SYNC_ASSIGNEE=false
STELLAR_WRITEBACK_SYNC_SEVERITY=false
STELLAR_SYNC_ALLOWED_SEVERITIES=Critical,High
STELLAR_MULTI_TENANT_ENABLED=true
STELLAR_MULTI_TENANT_STRICT=true
STELLAR_POLL_SOURCE_ID=stellar
```

### Conflict / noise guards

- Status writeback runs only when Jira **workflow** status changes (tracked per issue). Assignee sync / Case Activity comments bump Jira `updated` but must **not** re-apply Open/New onto Stellar.
- First time an issue is seen, non-terminal workflow is recorded as baseline without pushing status onto Stellar (inbound mirror owns Stellar→Jira for open work).
- If Jira is already **Resolved / Closed / Done / Cancelled**, status writeback still applies (duty may close only in Jira), and inbound mirror will not reopen it from a non-terminal Stellar status.

## Severity gating & deferred create

- **Create** only for `STELLAR_SYNC_ALLOWED_SEVERITIES` (default Critical,High).
- **Low/Medium do not enter** the `deferred_create` permanent queue. If severity later rises, `modified_at` changes and the normal poll creates the ticket.
- Severity-gated skips **do not** archive full alert bundles (avoids DB bloat); create/escalation paths still archive.
- Snapshot **retention**: each kept version stays full-fidelity; non-milestone versions are pruned (`CASE_ARCHIVE_AUTOPRUNE`, `./Tools/run case-archive-gc`). See `DECISION_LAYER.md`.
- `deferred_create` remains for **failed Jira create** and **Decision defer/suppress** retries only.

## Description & notify

- Jira Description and Stellar **Email/LINE body** share `stellar_case_detail_lines()` (`app/stellar/jira_draft.py`).
- Optional AI sections may wrap that body when `SOC_NOTIFY_AI_*` is enabled (Groq).

### Notify matrix (Critical/High create)

| Channel | When | Recipients | Content |
|---------|------|------------|---------|
| SOC Email + LINE | After Jira create | `SOC_NOTIFY_TO` / `LINE_NOTIFY_TO` | Case detail (+ optional Groq sections) |
| MaiAgent full-case | After same create (extra) | LINE: `MAIAGENT_NOTIFY_LINE_TO` or **shared** `LINE_NOTIFY_TO`; optional email `MAIAGENT_NOTIFY_EMAIL_TO` | Separate `MaiAgent AI 分析:` Root Cause |
| Low/Medium | Never (no ticket) | — | No SOC notify; no MaiAgent unless legacy all-cases is on |

- Optional **MaiAgent full-case** (`MAIAGENT_NOTIFY_ENABLED`): after Critical/High
  Jira create only, runs Root Cause analysis on the whole case and pushes a
  separate `MaiAgent AI 分析:` LINE message. Empty `MAIAGENT_NOTIFY_LINE_TO`
  shares `LINE_NOTIFY_TO` with SOC; optional `MAIAGENT_NOTIFY_EMAIL_TO` is extra
  email only (never uses `SOC_NOTIFY_TO`). Does not change Groq text or SOC
  recipients. Default async (`MAIAGENT_NOTIFY_ASYNC=true`) so the cycle is not
  blocked.
- `MAIAGENT_NOTIFY_ONLY_WITHOUT_CORTEX_CASE_ID=true` can limit MaiAgent to cases
  without a Cortex case ID.
- Optional legacy all-case mode (`MAIAGENT_ALL_CASES_ENABLED`) analyzes every
  registry-approved case first observed after enablement, including Low/Medium.
  Keep **false** when SOC only handles Critical/High. Each case is claimed once
  in `maiagent_case_delivery`; failed analysis/delivery retries after
  `MAIAGENT_ALL_CASES_RETRY_SECONDS`.
- All-case results require an explicit `MAIAGENT_ALL_CASES_LINE_TO` (never falls
  back to `LINE_NOTIFY_TO`). Prefer post-create MaiAgent instead.
- **AIxSOC Decision block is not appended** to Jira Description (`DECISION_APPEND_JIRA_DESCRIPTION=false`; WIP).
- A short **Decision checklist comment** may be posted after create (`DECISION_JIRA_COMMENT_ON_CREATE=true`).
- Outcome-tag reminder comments default **off** (`DECISION_OUTCOME_REMIND_ON_WRITEBACK=false`).

### Stellar native AI Summary

- `STELLAR_AI_SUMMARY_ENABLED=true` reads Stellar's native Case AI Summary through
  MCP `getCaseDetail(include=aiSummary)` for linked Critical/High cases.
- Full MCP payloads are stored with the latest case snapshot and in delivery state.
  Jira receives a concise `Stellar Cyber AI Summary` comment when
  `STELLAR_AI_SUMMARY_JIRA_COMMENT=true`; Description is unchanged.
- AI Summary generation is asynchronous. Missing `ai_case_triage` results retry after
  `STELLAR_AI_SUMMARY_RETRY_SECONDS` up to `STELLAR_AI_SUMMARY_MAX_ATTEMPTS`.
- MCP, archive, or Jira-comment failures are fail-open and do not block Jira creation.
- This native payload is distinct from Groq SOC notify, MaiAgent, and Decision AI text.

## Decision Layer

- Still runs before create when `DECISION_ENABLED=true` (labels, priority, defer/suppress, audit).
- Registry `customer_code` is canonical for rules and Decision persistence; similar-case
  history is filtered by the same code to prevent cross-tenant context reuse.
- SOC notify AI receives the Decision brief and seeds `decision_events` (`DECISION_RECORD_AI`);
  default is one LLM call after create (set `DECISION_RUN_AI_ON_CREATE=true` only if you want AI
  before the Jira ticket exists).
- Do not treat `docs/archive/AI_Security_Decision_Platform_Notes.md` as runtime spec.
- Code defaults enable Decision and case archive even when variables are absent:
  `DECISION_ENABLED=true`, `CASE_ARCHIVE_ENABLED=true`.

## Webhooks (optional, not required for cycle sync)

| Endpoint | Role |
|----------|------|
| `POST /v1/webhooks/jira-stellar` | Faster Jira→Stellar writeback; **required for Jira comment → Stellar** (cycle writeback covers Status fields only) |
| `POST /v1/webhooks/line` | LINE ID discovery only |

There is **no** Stellar→Jira case webhook in this repo; inbound uses poll.

## Read-only case API (`/v1/ai-data`)

Local FastAPI (`./serve_api`) can expose archived case snapshots for external AI/tools:

| Endpoint | Role |
|----------|------|
| `GET /v1/ai-data/cases` | List linked cases from SQLite |
| `GET /v1/ai-data/cases/{jira_key}` | Case bundle sections from latest snapshot |
| `GET /v1/ai-data/cases/{jira_key}/alerts` | Paginated alerts from that snapshot |

Auth: `AI_DATA_API_TOKEN` (Bearer / `X-AI-Data-Token`); if unset, loopback only. Read-only; does not call Stellar live.

## Docs map for agents

| Read | Skip |
|------|------|
| `docs/CURRENT_RUNTIME.md` (this file) | `docs/archive/**` |
| `docs/MAINTENANCE.md` | Historical design notes |
| `docs/DECISION_LAYER.md` (if changing Decision) | |
| `docs/ACTUAL_ARCHITECTURE_FOR_SPEC.md` (if rewriting product/MVP specs) | |
| `README.md`, `env.example` | |
| `AGENTS.md` | |

See also `docs/README.md`.
