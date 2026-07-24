> **AI AGENTS — DO NOT READ BY DEFAULT (Tier 3).**  
> Long **implemented product spec**; overlaps [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md).  
> Use `CURRENT_RUNTIME.md` + code for coding/ops. Open **only** if user asks for the full product specification document.

# Stellar–Jira Security Decision Platform 規格

- 文件版本：v1.2（runtime-aligned；MaiAgent full-case + shared LINE）
- 文件狀態：Implemented / Production Baseline
- 文件日期：2026-07-16
- 適用倉庫：`stellar-jira`
- Runtime source of truth：`docs/CURRENT_RUNTIME.md` + `.env` + `app/`

## 1. 產品定位

本系統是已上線的 **Stellar Cyber ↔ Jira AIxSOC 同步與自動化中樞**，
並在建票路徑嵌入可選的 Decision Intelligence 與 AI 通知。

系統不是通用 Event Ingestion Platform，也不是獨立 Human Review Gate：

- 入站來源是 Stellar Cyber Cases API，採 `modified_at` poll。
- Jira Cloud `AIXSOC` 是案件管理與人工覆核介面。
- Decision Layer 提供 escalation、playbook、通知、advisory 與 audit。
- LLM 只產生說明／通知文字，不可覆寫規則結果或自動執行隔離。
- 本 repo 不直接同步 Cortex XDR API；Cortex 類型告警可經 Stellar case
  進入同步與報表。

## 2. MVP 目標

1. 穩定同步 Stellar case 與 Jira issue。
2. 多個 Stellar tenant 共用同一 Jira project，但資料歸屬、報表與統計可分離。
3. 僅對符合 severity／Decision policy 的新 case 建票。
4. Status 雙向同步；Assignee 僅 Stellar → Jira。
5. 保留 case snapshot、Decision audit 與 outcome 關聯。
6. 提供 Groq SOC 廣播，以及 Critical/High 建票後的 MaiAgent full-case 額外分析
   （可與 SOC 共用 `LINE_NOTIFY_TO`）。
7. 所有 AI、通知與非必要 enrichment 失敗時 fail-open，不阻斷核心同步。

## 3. Runtime 架構

```text
Stellar Cyber API
  │ global modified_at poll
  ▼
Tenant Registry classification
  ├─ valid + enabled → tenant policy/customer_code
  └─ unknown/mismatch/disabled → SQLite quarantine
  │
  ▼
Inbound processing
  ├─ linked case → Status/Assignee/Activity mirror
  └─ new Critical/High case
       → fetch bundle
       → archive snapshot
       → optional Decision Knowledge + Rules
       → create Jira AIXSOC issue
       → Decision checklist comment
       → SOC Email/LINE (optional Groq)          # 原機制
       → MaiAgent full-case (optional; same LINE) # 額外一則
  │
  ▼
Incremental Jira writeback
  └─ workflow Status (+ optional resolution tag) → Stellar
```

服務：

- systemd：`ticket-api-stellar-jira.service`
- log：`/var/log/stellar_jira.log`
- state DB：`data/stellar_sync_state.sqlite`
- large snapshots：`data/case_archive/`

## 4. Multi-tenant 規格

### 4.1 Registry

權威設定：`config/stellar_tenants.json`。

每個 tenant 至少包含：

- `source_id`：CLI、Jira label、report selector 的穩定識別。
- `tenant_id`：Stellar `cust_id`；嚴格分類主鍵。
- `tenant_name`：Stellar 顯示名稱；與 case 交叉驗證。
- `customer_code`：案件編號、summary、Decision／報表的 tenant 維度。
- `enabled` / `sync_enabled` / `reporting_enabled`。
- `products`：可產出的報表產品。
- `jira_project_key`：選用 override；production tenants 共用 `AIXSOC`。
- `allowed_severities` / `jira_labels`：選用 per-tenant policy。

目前啟用：

| source_id | tenant_name | customer_code | products | Jira |
|-----------|-------------|---------------|----------|------|
| `jjnet` | `JJNET` | `JJNET` | darktrace, cortex | `AIXSOC` |
| `jjnet-edr` | `JJNET-EDR` | `JJEDR` | cortex | `AIXSOC` |

### 4.2 Classification

當 `STELLAR_MULTI_TENANT_ENABLED=true`：

1. Cases poll 不傳單一 `tenant_id`。
2. `case.cust_id` 必須唯一對到 registry `tenant_id`。
3. 若 case 同時有 `tenant_name`，必須與 registry 完全相符（忽略大小寫）。
4. Unknown ID、name mismatch 或 disabled tenant 不得建 Jira。
5. 被拒絕 case 寫入 `tenant_case_quarantine`；tenant 啟用後可重放。

`STELLAR_MULTI_TENANT_STRICT=true` 是 production 必要設定。

### 4.3 Global sync identity

- Poll watermark 與 Jira mapping 保留全域 `source_id=stellar`。
- 不將 existing links 改成 per-tenant source，避免重複建票與 writeback 失聯。
- `incident_jira` 另外保存 `tenant_source_id`、`tenant_id`、
  `tenant_name`、`customer_code`。
- Similar Decision history必須同時以 `customer_code` 隔離。

## 5. Jira 規格

所有 tenant 可使用同一 Jira project。

新建 issue 必須包含：

- project / issue type
- Summary：`[{severity}][{event_name}][{customer_code}]`
- Description：與 SOC 通知共用 `stellar_case_detail_lines()`
- Tenant / Tenant ID（Description）
- `tenant-<source_id>` label
- `stellar-cyber`、`aixsoc`、`stellar-case-<id>` labels
- Severity、Stellar status、alert name、middleware case ID 等已設定欄位
- Optional Decision labels／priority

Middleware Case ID：

```text
XSOC-{customer_code}-{YYMMDD}-{daily_sequence}
```

同步矩陣：

| Field | Stellar → Jira | Jira → Stellar |
|-------|----------------|----------------|
| Status | yes | yes |
| Assignee | yes | no |
| Severity | create only | no |
| Case Activity | Jira comment | — |
| Jira comment | — | webhook only |
| Resolution tag | create/read | terminal writeback 可映射為 Stellar tags/outcome |

Decision 全文預設不寫入 Description；建票後可新增 checklist comment。

## 6. Severity、retry 與 watermark

- 預設只為 `Critical,High` 建票。
- Low/Medium 不進永久 deferred queue；severity escalation 更新
  `modified_at` 後由正常 poll 建票。
- `deferred_create` 僅用於 Jira create failure 或 Decision defer/suppress。
- Jira create 先以 SQLite claim 防止同時重複建票。
- 失敗 case 會限制 watermark 前進，確保可重試。
- API 5xx／timeout 依 `STELLAR_HTTP_MAX_RETRIES` 重試。
- Inbound Stellar failure 時略過該輪 writeback，避免對故障平台加壓。

## 7. Decision Intelligence

流程：

```text
case bundle
  → snapshot
  → Knowledge (Sigma/MITRE/assets/same-tenant history)
  → deterministic Rules
  → DecisionResult
  → Jira labels/priority + notify routing + audit
```

`DecisionResult` 主要輸出：

- `action`: create_ticket / escalate / defer / suppress
- `escalation`: L1 / L2 / IR
- `notify_customer` / `notify_internal`
- `isolate_host`（advisory only）
- `playbook_id` / `confidence`
- `rule_hits` / `knowledge_hits`
- `jira_labels` / `jira_priority`

規格邊界：

- Rules/Knowledge 決定 action；LLM 不可覆寫。
- `isolate_host` 只會產生 advisory label，不會呼叫端點隔離。
- `DECISION_ONLY_WITHOUT_CORTEX_CASE_ID=true` 時，有 Cortex case ID 的
  bundle 跳過 Decision，但仍可建票／通知。
- Outcome TP/FP 機制存在，但不是建票當下必填輸出。

## 8. AI 與通知

### 8.1 SOC Notify AI

- Provider：Groq/OpenAI-compatible。
- 收件者：`SOC_NOTIFY_TO`、`LINE_NOTIFY_TO`。
- 目的：SOC broadcast 的摘要、事件描述、建議處置。
- Decision brief 可提供給 LLM，使文字與規則結果一致。
- `SOC_NOTIFY_AI_FAIL_OPEN=true` 時 AI failure 不阻止通知。

### 8.2 MaiAgent full-case（建票後額外分析）

- 觸發：僅 Critical/High **Jira 建票成功後**（與 SOC 建票門檻相同）。
- API：MaiAgent chatbot；輸出 plain-text Root Cause（整案＋alerts），推送標題
  `MaiAgent AI 分析:`。
- LINE：`MAIAGENT_NOTIFY_LINE_TO` 空白時**共用** `LINE_NOTIFY_TO`（SOC 頻道）；
  有填則覆寫。
- Email：可選 `MAIAGENT_NOTIFY_EMAIL_TO`（不使用 `SOC_NOTIFY_TO`）。
- 不修改 Groq SOC 文字、SOC recipients、Jira Decision 或規則。
- 預設 async／fail-open，不阻塞 automation cycle。

### 8.3 MaiAgent all-case channel（legacy／非預設）

- 可對啟用後首次觀察到的每個合法 tenant case 分析一次，**含 Low/Medium**。
- SOC 目前只處理 Critical/High 時請保持 `MAIAGENT_ALL_CASES_ENABLED=false`。
- 第一個 configured cycle 建立 baseline，不補送歷史 case。
- SQLite claim 防止重複；delivery failure 依設定間隔重試。
- `MAIAGENT_ALL_CASES_LINE_TO` 必填（獨立收件人）；空白則 all-cases 不啟用，
  不會沿用 `LINE_NOTIFY_TO`。
- 結果另推 `MaiAgent AI 分析:`，不改寫原 SOC/Groq 或 post-create MaiAgent。

## 9. 資料與稽核

SQLite 主要資料：

- `incident_jira`：case ↔ Jira link + tenant ownership。
- `meta`：global watermark、cycle health、tenant stats、deferred IDs。
- `tenant_case_quarantine`：無法安全分類的 case。
- `maiagent_case_delivery`：全案例分析 baseline／pending／delivered／failed 狀態。
- `stellar_case_snapshots`：完整 evidence snapshot／file pointer。
- `decision_events`：Decision、AI sections、outcome、snapshot/Jira link。

Snapshot milestone retention：

- Decision reference
- earliest / latest
- Jira-linked
- first snapshot per severity

保留的 snapshot 必須 full-fidelity；不得只保存 LLM 摘要。

## 10. Tenant 報表與統計

CLI：

```bash
./Tools/run report-monthly --tenant <source_id> --product <darktrace|cortex> --month YYYY-MM
./Tools/run report-export  --tenant <source_id> --product <darktrace|cortex> --month YYYY-MM
```

- Stellar rows 使用 tenant API scope + `tenant_name` client-side validation。
- CSV/JSON summary 必須包含 `tenant_source_id`、`customer_code`、`product`。
- 月報 Jira MTTR 使用 `tenant-<source_id>` label，即使共用 `AIXSOC`
  仍維持 tenant scope。
- 新票自動帶 tenant label；舊 Jira 若尚未回填 label，不會納入
  label-scoped historical MTTR。

## 11. Tenant 管理

```bash
./Tools/run tenant-list
./Tools/run tenant-discover [--apply]
./Tools/run tenant-validate
./Tools/run tenant-enable <source_id>
./Tools/run tenant-disable <source_id>
./Tools/run tenant-health
./Tools/run tenant-quarantine
./Tools/run tenant-backfill [--apply] [--assume <source_id>]
```

- `discover --apply` 新增的 tenant 預設 disabled。
- `enable/disable` 原子更新 registry。
- `tenant-backfill` 只補 SQLite ownership，不修改 Jira issue。

## 12. Security requirements

1. API keys 只存在 `.env`／secret store，不得寫入 Jira、log 或 export。
2. Tenant `cust_id` 為權威，禁止在未知 ID 時以名稱猜測歸屬。
3. Decision similar history 必須以 tenant `customer_code` 過濾。
4. Unknown/mismatch tenant 必須 quarantine，禁止 fail-open 建票。
5. Jira project 可共用，但 labels、Description、state DB 與 reports 必須保存 tenant ownership。
6. LLM output 視為不可信文字，不得執行命令或高風險操作。
7. Webhook 必須驗證 `STELLAR_WEBHOOK_TOKEN` / `SYNC_API_TOKEN`。
8. LINE webhook 必須驗證 signature。

## 13. Operations and acceptance

部署後驗證：

```bash
./Tools/run compile-check
./Tools/run stellar-verify
./Tools/run tenant-validate
./Tools/run tenant-health
./Tools/run stellar-sync-dry-run
./Tools/run tenant-quarantine
```

最低驗收：

- Registry identity validation 無錯誤。
- Global poll 能分類所有回傳 cases。
- Unknown/mismatch case 不建 Jira。
- 同一 case 不重複建票。
- 新票含正確 tenant label／Description。
- Status mirror/writeback 不因 multi-tenant 中斷。
- Report 指定 tenant 後不包含其他 tenant rows。
- MTTR JQL 包含該 tenant label。
- AI failure 不阻斷核心同步。
- 全部 unit tests 通過，systemd service active。

## 14. Out of scope

- 獨立 Web tenant management UI（目前為 JSON registry + CLI）
- 通用 JSON Event Ingestion API
- Cortex XDR 直接同步 client
- 跨產品 normalized event platform
- 自動隔離、停用帳號、刪檔、封鎖 IP
- 多 Agent 自主處置
- 獨立 SDP RBAC／Human Review Gate
- 大規模 fine-tuning／Golden Dataset 作為短期 Go/No-Go

## 15. 文件權威順序

若文件衝突：

```text
running .env + docs/CURRENT_RUNTIME.md + code
  > docs/MAINTENANCE.md
  > this specification
  > README
  > docs/archive
```

歷史文件位於 `docs/archive/`，不得用於判斷 production runtime。
