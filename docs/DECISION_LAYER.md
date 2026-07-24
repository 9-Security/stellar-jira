> **AI AGENTS — Tier 2.** Read **only** when changing Decision Layer (`app/decision/`).  
> Sync/runtime: use `CURRENT_RUNTIME.md` instead.

# AIxSOC Decision Intelligence

> Runtime sync context: [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md).  
> Product brainstorm notes are archived — do not use `docs/archive/AI_Security_*` for implementation.

Decision Layer sits between Stellar case intake and Jira create / SOC notify.
It turns heuristic + policy into **machine-verifiable decisions** and seeds a
**Decision Dataset** for later fine-tuning.

In multi-tenant mode, the registry supplies the canonical `customer_code`.
Decision rules and similar-case history are filtered by that code, so one
tenant's prior decisions are not used as similarity context for another.
The global sync `source_id=stellar` remains the stable case/Jira mapping partition.

## Pipeline

```text
Stellar case bundle
        │
        ▼
 stellar_case_snapshots (raw: case + alerts + observables + summary)
        │
        ▼
 Knowledge (Sigma catalogue, MITRE playbooks, asset criticality, similar cases).
Sigma entries may set ``require_blocked`` / ``require_not_blocked`` so WildFire that
is already blocked maps to ``PB-IR-MALWARE-BLOCKED``. Similar-case ranking prefers
peers that already have TP/FP outcomes.
        │
        ▼
 Rules engine (config/decision_rules.json)
        │
        ▼
 DecisionResult → Jira labels/priority + notify routing + decision_events audit
        │
        ▼
        (optional) SOC notify AI text → same decision_events row
        (Decision brief is passed into the LLM; one call unless notify is skipped)
        │
        ▼
 Jira resolve / writeback → outcome (TP/FP / root cause)
```

**Product focus (current):** duty-facing value at create time — labels + a short
Jira **Decision comment** with playbook checklist. Outcome / Dataset / Go-No-Go
metrics remain available but are **not** the primary push until resolution-tag
(or equivalent) labeling is adopted.

## Enable

Defaults are on. In `.env`:

```bash
DECISION_ENABLED=true
DECISION_APPEND_JIRA_DESCRIPTION=false   # WIP: keep false so Jira Description stays clean
DECISION_RULES_PATH=config/decision_rules.json
DECISION_KNOWLEDGE_PATH=config/decision_knowledge.json
DECISION_ASSETS_PATH=config/decision_assets.json
DECISION_RECORD_AI=true
DECISION_RUN_AI_ON_CREATE=false   # true = LLM before Jira create (adds latency); prefer notify-path merge
DECISION_JIRA_COMMENT_ON_CREATE=true   # short Decision duty checklist after create
DECISION_ONLY_WITHOUT_CORTEX_CASE_ID=true  # only Stellar-elevated (no Cortex case_id); skip XDR-linked
DECISION_OUTCOME_ON_WRITEBACK=true
DECISION_OUTCOME_REMIND_ON_WRITEBACK=false  # path C default: off until Dataset loop is active
CASE_ARCHIVE_ENABLED=true
CASE_ARCHIVE_MAX_BYTES=2097152
CASE_ARCHIVE_DIR=data/case_archive
CASE_ARCHIVE_AUTOPRUNE=true   # keep milestones only (full alerts per kept version)
```

`DECISION_ONLY_WITHOUT_CORTEX_CASE_ID=true` means Decision runs only when **no** alert in the
bundle has a Cortex XDR ``case_id`` (Stellar rule-elevated cases, e.g. ticket 1214).
Cases that already carry a Cortex case id (XDR blocked / detect-only, e.g. 1220/1222) still
create Jira tickets but **skip** Decision labels/checklist.
`DECISION_APPEND_JIRA_DESCRIPTION=false` means Decision analysis is **not** appended to the
Jira issue description (labels/priority/defer still apply). See `docs/CURRENT_RUNTIME.md`.

`stellar_case_snapshots` stores the Stellar platform-normalized bundle (case + alerts).
Large bundles (> `CASE_ARCHIVE_MAX_BYTES`) are written under `data/case_archive/` with a
SQLite pointer (`storage_mode=file`). `decision_events.snapshot_id` links decision rows
to the raw snapshot.

**Retention (evidence milestones):** each kept snapshot stays **full-fidelity** (no
in-bundle alert content dedupe). Per case we keep only:

- snapshots referenced by `decision_events`
- earliest + latest `modified_at`
- any row with `jira_key`
- first snapshot for each distinct severity

`CASE_ARCHIVE_AUTOPRUNE=true` applies this after each write. Historical spam:
`./Tools/run case-archive-gc` (dry-run) then `--apply`.

**Synced cases:** when severity rises after Jira ticket creation (e.g. Medium → High),
the sync runner re-fetches the bundle, stores a new snapshot (or replaces the row at the
same `modified_at` when Stellar did not bump it), and optionally persists a new
`decision_events` row (`CASE_ARCHIVE_ON_SEVERITY_ESCALATION`,
`DECISION_REEVAL_ON_SEVERITY_ESCALATION`). Routine alert growth on unchanged severity
does not trigger re-snapshot.

Isolation is **advisory only** (`isolate_host` → Jira label `isolation-advisory`).
Malware already blocked uses playbook ``PB-IR-MALWARE-BLOCKED`` (no re-isolate advisory).
Nothing in this layer auto-isolates a host.

## CLI

```bash
# Preview decision for one case
./Tools/run decision-evaluate --case-id <stellar_case_id>
./Tools/run decision-evaluate --case-id <id> --persist --ai

# Manual outcome (closes Dataset loop)
./Tools/run decision-outcome --jira-key AIXSOC-123 --true-positive false --root-cause "授權軟體安裝"
./Tools/run decision-outcome-backfill              # dry-run from Jira resolution tags
./Tools/run decision-outcome-backfill --apply

# Export fine-tune / analysis dataset (joins snapshots when available)
./Tools/run decision-dataset --out data/decision_dataset.jsonl

# Pilot audit / ROI report
./Tools/run decision-pilot-report --out data/decision_pilot_report.md
./Tools/run decision-pilot-report --format json --out data/decision_pilot_report.json

# Snapshot retention GC (default dry-run)
./Tools/run case-archive-gc
./Tools/run case-archive-gc --apply
./Tools/run case-archive-gc --case-id <stellar_case_id> --apply
```

## Customizing assets (CMDB-lite)

Edit `config/decision_assets.json`:

```json
{
  "default_criticality": "medium",
  "hosts": {
    "dc01": { "criticality": "critical", "role": "domain-controller" }
  }
}
```

High/critical assets bump escalation toward L2 and may enable customer notify.

## Go / No-Go metrics

The pilot report tracks:

- mis-escalation rate (L2/IR later marked FP)
- customer notify rate
- defer/suppress rate
- **labeled** outcome coverage (TP/FP from resolution tag or CLI)

Target from the product plan: **≥20% improvement** on mis-escalation after ~8 weeks
of internal use before external commercialisation.

## Outcome closed loop

Writeback on terminal Jira statuses stamps `decision_events` and maps resolution
tag (`customfield_10201`: False Positive / True Positive / Benign) into TP/FP.
Recent Jira comments are also scanned for TP/FP / `root cause:` phrases.
Empty stamps no longer inflate coverage. Backfill historical tickets with
`decision-outcome-backfill`.

**Duty UX:** after create, a short Decision **checklist** comment is posted
(`DECISION_JIRA_COMMENT_ON_CREATE`) so Description stays clean. Outcome-tag
reminders are **off by default** (`DECISION_OUTCOME_REMIND_ON_WRITEBACK=false`);
turn on when the Dataset loop is an active ops goal.

Pilot report lists **unlabeled resolved** tickets for follow-up when you care.

## Decision ↔ SOC notify AI

Rules/Knowledge decide; the LLM only explains. On create:

1. Decision evaluate (optional `DECISION_RUN_AI_ON_CREATE` — usually **false**)
2. Jira create
3. SOC notify runs AI **once**, with a `decision` block in the case JSON (escalation /
   playbook / isolate advisory) so the handoff matches labels
4. If notify is skipped or disabled, and `DECISION_RECORD_AI=true`, AI still runs once
   post-create to seed `decision_events.ai_json`
5. Precomputed sections from step 1 are reused in step 3 (no second LLM call)

MaiAgent (`MAIAGENT_NOTIFY_*`) is an optional fail-open **full-case** channel that
runs only after Critical/High Jira create. It pushes a separate
`MaiAgent AI 分析:` message; empty `MAIAGENT_NOTIFY_LINE_TO` shares
`LINE_NOTIFY_TO` with SOC. Optional `MAIAGENT_NOTIFY_EMAIL_TO` is extra email
only. It does not seed or override `DecisionResult` or the Groq SOC broadcast.
Keep `MAIAGENT_ALL_CASES_ENABLED=false` unless you intentionally want Low/Medium
analysis without a Jira ticket.
