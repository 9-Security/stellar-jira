> **OUTDATED / HISTORICAL — DO NOT USE FOR RUNTIME**
>
> Archived 2026-07-13. Description changes listed here were largely **implemented**.
> Email/LINE now share Jira Description format (`stellar_case_detail_lines`).
> For live behavior read **`docs/CURRENT_RUNTIME.md`** only.
> AI agents: **do not load this file** unless the user asks for history.

# Pending improvements (batch later) — ARCHIVED

**Scope:** Jira issue **description display only** (`stellar_case_detail_lines` in `app/stellar/jira_draft.py`).  
Does **not** change Email/LINE (XMDR template), Jira custom fields, summary, or Stellar↔Jira sync rules — except one small parser fallback when hiding `Stellar Case ID` from description text (see below).

**Implemented 2026-07-09:** observables host+IP, simplified labels, hidden header lines, AIxSOC Ticket ID, hidden Assignee, `Detail:` block (host/user/process/file), writeback label fallback. See git history on `app/stellar/jira_draft.py`.

Tracked items below — open items to implement in a future pass.

## Jira description — replace Created/Modified with 偵測時間 (evaluate only)

**User intent:** Hide `Created:` and `Modified:` in Jira description; show a single **事件偵測時間** line instead.

### Current

```
Created: 2026-07-08 01:44 UTC
Modified: 2026-07-08 12:39 UTC
```

- Source: Stellar `case.created_at` / `case.modified_at` (epoch ms).
- Formatter: `_ms_to_iso()` → always **UTC**, `YYYY-MM-DD HH:MM UTC`.
- **Created** = case first opened in Stellar.
- **Modified** = last Stellar case update (status, severity, assignee, etc.).

### Desired

```
偵測時間: Jul 9th 2026 09:44:00
```

(or equivalent — one line only; exact format TBD at implementation)

### Recommended data source

| Option | Field | Pros | Cons |
|--------|-------|------|------|
| **A (recommended)** | `case.created_at` | Same as XMDR Email/LINE `偵測時間` for Stellar (`notify_ticket_created` maps `created_at` → detection time). One meaning across Jira + notify. | Not the earliest sub-alert timestamp if case was opened later than first alert. |
| B (future) | Earliest alert `detection_timestamp` in bundle | Closer to “first seen” | Needs alert parsing; may diverge from XMDR unless notify is updated too. |

**Recommendation:** Option **A** unless product asks for alert-level time.

### Timezone / format (decide at implementation)

| Channel | Today |
|---------|--------|
| Jira description | UTC `2026-07-08 01:44 UTC` |
| Email/LINE XMDR | `Asia/Taipei` (`STELLAR_CASE_ID_TIMEZONE`), `Jul 9th 2026 15:30:00` via `_format_detection_time()` |

**Options:**

1. **Align with XMDR** — reuse `_format_detection_time(created_at, timezone_name=stellar_case_id_timezone)` and label `偵測時間:` (consistent with SOC mail/LINE).
2. **Keep UTC in Jira only** — `偵測時間: 2026-07-09 01:44 UTC` (simpler diff, but inconsistent with notify).

### Impact

| Area | Effect |
|------|--------|
| Jira description | Display only; edit `stellar_case_detail_lines` in `jira_draft.py`. |
| Email / LINE | **No change** (already has `偵測時間`). |
| Sync / writeback | **No change** — nothing parses `Created:` / `Modified:` lines. |
| Polling / watermark | **No change** — still uses `modified_at` internally. |
| Tests | Update `tests/test_jira_draft_description.py`. |

### What analysts lose in Jira UI

- **Modified** no longer visible in description after create (Stellar console still shows it; automation still tracks it).

### Implementation sketch (when approved)

1. Remove the two `_ms_to_iso(created_at/modified_at)` lines.
2. Add one line: `偵測時間: {_format_detection_time(case.get('created_at'), ...)}` — either import from `notify/ticket_created` or move shared formatter to `app/dates.py` to avoid circular imports.
3. Confirm label: `偵測時間:` vs `事件偵測時間:` (match XMDR).

**Status:** **Implemented 2026-07-09** — `format_detection_time()` in `app/dates.py`; Jira description uses `case.created_at`, `Asia/Taipei`, label `偵測時間:`; also added `自動回應結果:` and removed `事件狀態:`.

**Recorded:** 2026-07-09

## Jira / SOC description — observables host format — DONE (2026-07-09)

**Context:** Stellar may return multiple `host` entries with the same `hostname` but different `ip` (e.g. case 1123: Gary-Kuei on 192.168.0.98 and 192.168.233.222). Current output only shows hostname, so lines look duplicated.

**Current** (`app/stellar/jira_draft.py` → `_observable_lines`):

```
host: Gary-Kuei
host: Gary-Kuei
```

**Desired:**

```
host: Gary-Kuei (192.168.0.98)
host: Gary-Kuei (192.168.233.222)
```

**Rules:**

- If both `hostname` and `ip`: `host: {hostname} ({ip})`
- If only `hostname`: `host: {hostname}`
- If only `ip`: `host: {ip}`
- Applies to **Jira description** only (not Email/LINE body)

**Recorded:** 2026-07-07

## Jira / SOC description — simplify field labels

**Context:** User prefers shorter labels without English parenthetical.

**Current:**

```
事件狀態 (Stellar status): New
告警名稱 (Stellar name): LOLBIN process executed with a high integrity level
```

**Desired:**

```
事件狀態: New
告警名稱: LOLBIN process executed with a high integrity level
```

**Impact:** Display only (`app/stellar/jira_draft.py` → `stellar_case_detail_lines`). No sync/writeback/notify logic parses these strings. Jira custom fields unchanged.

**Recorded:** 2026-07-07

## Jira description — remove header lines (evaluate before change)

**User intent:** Hide lines from human-readable Jira description only — **not** delete Stellar case data, customer code, or SQLite mappings.

**Proposed hidden lines:**

- `Detection Source: Stellar Cyber`
- `Stellar Case ID: {24-hex}`
- `客戶代號: {JJNET}`

### Impact when implementing (display-only change)

| Line | Hide from description | Data still elsewhere |
|------|----------------------|----------------------|
| `Detection Source` | Safe | N/A (cosmetic) |
| `客戶代號` | Safe | Summary `[…][JJNET]`, 案件編號 field, notify/AI |
| `Stellar Case ID` | OK **if** code updated | SQLite `incident_jira`, Jira label `stellar-case-…`, Stellar API |

### Implementation note for `Stellar Case ID`

Today writeback / crash-recovery **reads this line from description text**. Hiding it requires a small code change: rely on SQLite mapping (normal path) and label/API fallback — not on description regex. Not “removing the case id”, just not showing it in description.

**Email / LINE:** unchanged (XMDR template; never showed these lines).

**Recorded:** 2026-07-07

## Jira description — rename ticket id label

**Change:** `Stellar Ticket ID: 1123` → `AIxSOC Ticket ID: 1123`

Value remains Stellar `ticket_id`; label only. No code parses this line.

**Recorded:** 2026-07-07

## Jira description — hide assignee (entire line)

**Change:** Do not show `Assignee:` in description at all (whether Unassigned or named).

Display only; no logic parses this line.

**Recorded:** 2026-07-07

## Jira description — rename Observables section

**Change:** `Observables (sample):` → `Detail:`

Sub-lines unchanged for now (`  - host: …`, `  - user: …`); data still from Stellar `GET /cases/{id}/observables` via `_observable_lines`.

Display only.

**Recorded:** 2026-07-07

## Jira description — Detail block (unified rule, all cases)

**Principle:** One fixed policy for every new case — no per-case tuning. Reuse existing notify logic where possible (`alert_fields.stellar_primary_file_path`).

### Detail section structure

```
Detail:
  - host: …
  - user: …
  - process: …    (optional)
  - file: …       (optional)
```

Max **8** bullet lines total (existing limit); omit empty types.

### Rules

| Line | Data source | Display rule |
|------|-------------|--------------|
| **host** | `observables.host[]` | Each entry: `host: {hostname} ({ip})` if both; else hostname or ip only. Show all hosts (not deduped by hostname alone). |
| **user** | `observables.user[]` | Each unique `username`, in API order. |
| **process** | `stellar_primary_file_path(bundle)` | **One line.** Basename of scored primary path (same algorithm as Email「檔案路徑」). Format: `process: {name}` or `process: {name} ({full path})` if path ≠ basename. Omit if no path. |
| **file** | `observables.file[-1]` | **One line** if `file_name` present **and** not duplicate of process line (same path/basename). Format: `file: {file_name}`. |

**Scoring improvements** (e.g. deprioritize `System32\explorer.exe`) happen only in `app/stellar/alert_fields.py` — Description and Email improve together.

**Supersedes:** observables `process[-1]` / latest-alert approaches (removed — not generalizable).

### Case 1123 preview (today’s scoring)

```
Detail:
  - host: Gary-Kuei (192.168.0.98)
  - host: Gary-Kuei (192.168.233.222)
  - user: GARY-KUEI\Gary Kuei
  - user: NT AUTHORITY\SYSTEM
  - process: explorer.exe
  - file: C:\Users\Gary Kuei\AppData\Roaming\Microsoft\SystemCertificates\Request\Certificates\AAEA9F96...
```

Note: `process` uses `stellar_primary_file_path` scoring (tuned 2026-07-07: deprioritize `System32` / `explorer.exe` / other common system binaries; prefer `Users\`, `Downloads\`, etc.).

**Recorded:** 2026-07-07

## Jira description — Detail: process (last observables entry only) — SUPERSEDED

See **Detail block (unified rule)** above.

**Recorded:** 2026-07-07

## Jira description — Detail: file (last observables entry only) — SUPERSEDED

See **Detail block (unified rule)** above.

**Recorded:** 2026-07-07
