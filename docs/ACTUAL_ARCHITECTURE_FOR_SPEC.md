> **AI AGENTS — DO NOT READ BY DEFAULT (Tier 3).**  
> Paste-to-ChatGPT handoff for **rewriting external specs**; duplicates `CURRENT_RUNTIME.md`.  
> Open **only** if user asks to rewrite Security Decision Platform spec or export architecture to another model.

# Stellar ↔ Jira AIxSOC — 實際運作與架構現況

> **用途：** 給外部模型／規格改寫用的**單一現況來源**（可整份貼給 ChatGPT）。  
> **日期：** 2026-07-16  
> **倉庫：** `stellar-jira`  
> **權威順序：** 本文件摘要 ≪ `docs/CURRENT_RUNTIME.md` + `.env` + `app/` 程式碼；若規格與 runtime 衝突，以 runtime 為準。  
> **規格基線：** `Security_Decision_Platform_MVP_Spec_v1.0.md` 已依本文與 runtime 對齊；`docs/archive/**` 仍只供歷史查考。

---

## 給 ChatGPT 的改寫指示（可連同本文一併貼上）

請把「Security Decision Platform MVP Spec」改寫成符合**下列實際系統**的規格，規則：

1. **只以 Stellar Cyber + Jira Cloud（AIXSOC）為主體**；忽略獨立 SDP 產品品牌、Cortex 雙軌、多 XDR Webhook Ingestion 產品線（除非標成「未來／非本 repo」）。
2. **系統定位**必須是：已上線的 **Stellar↔Jira 同步中樞**，其上掛載 **Decision Layer**；不是從零建 Event Ingestion API → Normalizer → Human Review Gate 的獨立決策平台。
3. **當前產品優先級（路徑 C）**：**值班在建票當下好用**（labels + Decision checklist 評論）。**不要**把 TP/FP classification、Golden Dataset、Human Review Gate、一致率驗收寫成 MVP 必達。
4. Decision 的 classification（TP/FP）**不是**建票當下的主輸出；主輸出是 escalation / playbook / notify / isolate-advisory / Jira labels。
5. LLM **只做說明與 SOC 通知文案**，不能覆寫規則決策，也不能自動隔離。
   MaiAgent 是 Critical/High 建票後的**額外** full-case 分析，可與 SOC 共用
   `LINE_NOTIFY_TO`；不可取代 Groq SOC 廣播，也不可分析未建票的 Low/Medium
  （除非明確開 legacy `MAIAGENT_ALL_CASES_*`）。
6. 刪除或降級：獨立 RBAC 角色產品、完整 Normalized Event Schema 產品、多 Agent、自動高風險處置、大規模 fine-tune。
7. 保留對齊的原則：規則優先於 AI、可稽核、raw snapshot、不把完整 raw payload 塞進 Jira Description、隔離僅建議。

---

## 1. 系統是什麼

| 項目 | 實際狀況 |
|------|----------|
| 名稱／角色 | Stellar Cyber → Jira AIxSOC **同步與自動化**；Decision／SOC 通知嵌在建票路徑 |
| 服務 | `ticket-api-stellar-jira.service` |
| 日誌 | `/var/log/stellar_jira.log` |
| 狀態庫 | `data/stellar_sync_state.sqlite` |
| Case archive | `data/case_archive/`（大型 bundle 檔） |
| 入站模式 | **Poll** Stellar cases（**無** Stellar→Jira case webhook） |
| Tenant 模式 | 單次全域 poll → registry 依 `cust_id` + `tenant_name` 嚴格分類 |
| Jira 專案 | `AIXSOC`（例） |
| Middleware Case ID | 形如 `XSOC-{customer}-{yymmdd}-{seq}`（Jira `customfield_10060`） |

**不是：** 通用 AI SOC、獨立 SDP 產品、自動隔離／封鎖主機、Cortex XDR 同步線（本 repo 不含）。

---

## 2. 實際架構圖

```text
                    ┌─────────────────────────┐
                    │   Stellar Cyber API     │
                    │  /connect/api/v1/cases  │
                    └───────────┬─────────────┘
                                │ poll (modified_at)
                                ▼
┌───────────────────────────────────────────────────────────────┐
│  stellar-jira automation cycle                                 │
│                                                                │
│  1) Inbound poll                                               │
│     ├─ Tenant Registry：unknown/mismatch/disabled → quarantine │
│     ├─ 已連結票：mirror Status / Assignee / Case Activity→Jira │
│     └─ 未連結 + Critical/High：                                 │
│           fetch case bundle (case+alerts+observables+summary)  │
│           → archive snapshot (milestone 保留)                    │
│           → Decision: Knowledge → Rules                        │
│           → create Jira issue (labels/priority)                │
│           → Decision checklist comment（值班步驟）               │
│           → SOC Email / LINE（可選 Groq；原機制不變）            │
│           → MaiAgent full-case（可選；Critical/High 建票後；     │
│              LINE 空白則共用 LINE_NOTIFY_TO）                     │
│                                                                │
│  2) Writeback（Jira updated 有變才做）                            │
│     Status (+ resolution tag) → Stellar                        │
│     結案時可 stamp decision_events outcome（TP/FP 視標註）         │
│                                                                │
│  3) sleep STELLAR_AUTOMATION_INTERVAL_SECONDS                  │
└───────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │  Jira Cloud (AIXSOC)    │
                    │  + Email / LINE notify  │
                    └─────────────────────────┘

可選 webhook（非 cycle 必要）：
  POST /v1/webhooks/jira-stellar  → 加速 writeback；
                                     Jira comment→Stellar **僅此路徑**
  POST /v1/webhooks/line          → LINE 收件人 ID 探索
```

### 與「理想 SDP」架構的對照

| SDP 規格常見磚塊 | 本系統 |
|------------------|--------|
| Event Ingestion API | **沒有**（改為 Stellar poll） |
| Event Normalizer（跨廠商統一 schema） | **沒有產品化**；直接用 Stellar case bundle |
| Context Enrichment 完整 | **薄**：JSON assets、Sigma/MITRE catalogue、similar decisions |
| AI Analysis Service（引擎前分類） | **沒有**；僅有 **SOC notify LLM**（建票後／可選） |
| Decision Engine | **有**（Knowledge + Rules → `DecisionResult`） |
| Human Review Gate UI／API | **沒有**；覆核在 **Jira／Stellar UI** |
| Decision Dataset Store | **有雛形**（`decision_events` + snapshots）；標註覆蓋率低 |
| Jira | **核心案件系統**（不是事後附加輸出而已） |

---

## 3. 自動化 Cycle（細節）

每輪：

1. **Inbound poll** — lookback 內 `modified_at` 有變的 Stellar cases  
2. **Tenant classify** — `cust_id` 主鍵、`tenant_name` 交叉驗證；不合法進 quarantine  
3. **Create** — 僅 tenant/global 允許的 severity（預設 `Critical,High`）  
4. **Poll mirror** — 已連結：Status／Assignee／Case Activity → Jira  
5. **Writeback** — 連結票且 Jira `updated` 變了：Status（+ resolution tag）→ Stellar  
6. Sleep interval（常為數秒～數十秒）

- Low/Medium：**不建票**、**不進**永久 deferred 佇列；升到 Critical/High 後靠 poll 再建。  
- `deferred_create` 只給：**建票失敗**、**Decision defer/suppress** 重試。  
- Severity 沒升、只是 alerts 變多：**不**重 archive／重 Decision。

### 欄位同步矩陣

| 欄位 | Stellar → Jira | Jira → Stellar |
|------|----------------|----------------|
| Status（workflow + 事件狀態） | yes | yes |
| Assignee | yes（email→accountId map） | **no** |
| Severity | 建票時 | **no** |
| Case Activity → Jira comment | yes（去重） | — |
| Jira comment → Stellar | — | **僅 webhook** |
| 新建票 | Critical/High only | — |

`STELLAR_JIRA_MASTER_AFTER_LINK=false`：連結後仍以 Stellar 作業為主（mirror Stellar→Jira）。

---

## 4. Decision Layer（實際）

路徑：`app/decision/`，設定：`config/decision_*.json`。

### 4.1 流程

```text
Stellar case + bundle
  → snapshot archive
  → Knowledge（Sigma / MITRE playbook hint / asset criticality / similar cases）
  → Rules（config/decision_rules.json）
  → DecisionResult
       action: create_ticket | escalate | defer | suppress
       escalation: L1 | L2 | IR
       notify_customer / notify_internal
       isolate_host（僅 advisory）
       playbook_id, confidence, rule_hits, knowledge_hits
       jira_labels, jira_priority
  → 套用到 Jira create fields（labels/priority；Description 預設不附加 Decision 全文）
  → 建票後留言：中文「值班檢查清單」（依 playbook）
  → （可選）SOC LLM 文案，context 含 decision brief → 寫回 decision_events.ai_json
```

### 4.2 決策原則（已落地）

- **規則／知識**決定升級與 playbook；**LLM 不覆寫** `action`。  
- **已阻擋（任一 alert Prevented/Blocked）** → disposition「已阻擋」；常見 playbook `PB-IR-MALWARE-BLOCKED`，**不**建議再隔離。  
- **隔離**只有 Jira label `isolation-advisory`，**絕不**自動隔離。  
- Low severity 規則可 **defer**（不建票）。

### 4.3 當前產品焦點（路徑 C，2026-07）

- **主推：** 建票 labels + **Decision checklist 評論**（告警名、處置狀態、主機、升級層級、建議步驟）。  
- **範圍閘門（預設開）：** `DECISION_ONLY_WITHOUT_CORTEX_CASE_ID=true`  
  - **有** Cortex `case_id`（XDR 阻擋／僅偵測）→ **不跑** Decision（仍建票／可通知）  
  - **沒有** Cortex `case_id`（Stellar 規則升 case，例 ticket **1214**）→ **才跑** Decision  
- **不主推：** 催值班填 Jira `resolution tag`、Dataset Go/No-Go、誤升級率驗收。  
- Outcome 機制**保留**（writeback／CLI／backfill），提醒評論預設關（`DECISION_OUTCOME_REMIND_ON_WRITEBACK=false`）。

### 4.4 Outcome / TP-FP（機制 ≠ 營運閉環）

| 來源 | 說明 |
|------|------|
| Jira `customfield_10201`（畫面名 **resolution tag**） | True Positive / False Positive / Benign → Dataset TP/FP |
| Jira 評論關鍵字 | 可作備援推斷 |
| CLI `decision-outcome` | 人工標註 |
| Stellar UI **Verdict** | 分析後可見（例 ticket 1222 = True Positive），但 **現行 Cases REST 讀不到** → **先略過** |

實務：值班常找不到／不填 resolution tag → **labeled outcome ≈ 0**；故 Dataset 閉環暫不當 MVP 主目標。

### 4.5 AI

| 種類 | 角色 |
|------|------|
| Decision Rules/Knowledge | 機器決策 |
| SOC Notify AI（Groq 等） | 建票後 Email/LINE 摘要／建議；英文 system prompt、**繁中回覆**；alerts 排序：阻擋→Malware→有 Cortex case_id |
| MaiAgent full-case | Critical/High 建票後額外 Root Cause；LINE 可共用 `LINE_NOTIFY_TO`；不修改 Groq／Decision |
| Stellar Case AI / Verdict | **未整合**（API 缺口） |

預設 `DECISION_RUN_AI_ON_CREATE=false`（避免建票前多等 LLM）；notify 路徑打一次並 seed `ai_json`。

---

## 5. 資料與儲存

| 儲存 | 內容 |
|------|------|
| `decision_events` | 決策列、context、ai_json、outcome_*、snapshot_id、jira_key |
| `stellar_case_snapshots` | case+alerts…；大檔落 `case_archive/` |
| Snapshot 保留策略 | milestone only：decision 引用、最早／最新、有 jira_key、各 severity 首筆；**不做** bundle 內 alert 內容去重 |
| Link 狀態 | 全域 source_id + Stellar case_id ↔ Jira key，另存 tenant source/id/name/customer_code |
| Tenant quarantine | unknown id、name mismatch、disabled case；保留 case JSON 供啟用後重放 |
| Decision similarity | 同一 global source 下再以 `customer_code` 隔離歷史 context |

---

## 6. Jira／通知（實際寫入什麼）

### 建票

- Summary 模板、嚴重程度、事件名稱、案件編號、Description（`stellar_case_detail_lines`，與 Email/LINE 同源）  
- Tenant：`tenant-<source_id>` label；Description 寫 Tenant / Tenant ID；所有 tenant 可共用 `AIXSOC`  
- Decision：**labels**（如 `decision-ir`、`pb-ir-malware-blocked`、`isolation-advisory`）、**priority**  
- **不**預設把 Decision 全文塞進 Description  
- **另留一則 comment**：值班檢查清單  

### 通知

- 建票成功後可寄 Email／LINE（可含 AI 三段：摘要／事件描述／建議處置）  

### 寫回 Stellar

- Status（含結案）；resolution tag 可對到 Stellar tags（對照表 `config/stellar_resolution_tag_map.json`）  
- Assignee／Severity 預設不由 Jira 回寫  

---

## 7. 主要程式／設定地圖

| 路徑 | 用途 |
|------|------|
| `app/stellar_sync/runner.py` | 自動化主循環 |
| `app/stellar/` | Stellar client、mirror、writeback、draft |
| `app/decision/` | pipeline、rules、knowledge、outcome、jira_notes、ai_bridge |
| `app/ai/` | SOC notify LLM + stellar context |
| `app/notify/` | Email／LINE／MaiAgent full-case |
| `config/decision_rules.json` | 規則 |
| `config/decision_knowledge.json` | Sigma／MITRE |
| `config/decision_assets.json` | 主機 criticality |
| `config/stellar_tenants.json` | Tenant identity、customer_code、enable policy、products、Jira project/labels |
| `docs/CURRENT_RUNTIME.md` | 同步 runtime 權威 |
| `docs/DECISION_LAYER.md` | Decision 操作說明 |
| `docs/MAINTENANCE.md` | 維運指令 |

CLI（`./Tools/run …`）：tenant `discover/list/validate/enable/disable/health/quarantine/backfill`、
`report-monthly`、`report-export`、Decision commands、`stellar-poll`、`notify-case`、
`maiagent-trial`、`maiagent-notify` 等。

---

## 8. 關鍵環境變數（摘要）

```bash
# 同步
STELLAR_MULTI_TENANT_ENABLED=true
STELLAR_MULTI_TENANT_STRICT=true
STELLAR_TENANTS_PATH=config/stellar_tenants.json
STELLAR_POLL_SOURCE_ID=stellar
STELLAR_SYNC_ALLOWED_SEVERITIES=Critical,High
STELLAR_MIRROR_ON_POLL=true
STELLAR_MIRROR_FULL_SCAN=false
STELLAR_JIRA_MASTER_AFTER_LINK=false
STELLAR_WRITEBACK_SYNC_STATUS=true
STELLAR_WRITEBACK_SYNC_ASSIGNEE=false

# Decision
DECISION_ENABLED=true
DECISION_APPEND_JIRA_DESCRIPTION=false
DECISION_JIRA_COMMENT_ON_CREATE=true
DECISION_ONLY_WITHOUT_CORTEX_CASE_ID=true
DECISION_RUN_AI_ON_CREATE=false
DECISION_RECORD_AI=true
DECISION_OUTCOME_ON_WRITEBACK=true
DECISION_OUTCOME_REMIND_ON_WRITEBACK=false

# Archive
CASE_ARCHIVE_ENABLED=true
CASE_ARCHIVE_AUTOPRUNE=true

# SOC AI（通知）
SOC_NOTIFY_AI_ENABLED=true   # 視環境

# MaiAgent full-case（Critical/High 建票後；選用）
MAIAGENT_NOTIFY_ENABLED=true
# MAIAGENT_NOTIFY_LINE_TO=     # 空白＝共用 LINE_NOTIFY_TO
# MAIAGENT_ALL_CASES_ENABLED=false  # 勿開（會含 Low/Medium）
```

完整列表見 `env.example`。

---

## 9. 已知限制與刻意不做

1. **無**獨立 Human Review Gate／覆寫 API／SDP RBAC。  
2. **無**跨廠商 Normalized Event 產品；輸入=Stellar bundle。  
3. **無**建票當下機器 TP/FP classification（與 SDP MVP 輸出 JSON 不同）。  
4. Outcome／Dataset **資料閉環弱**（依賴人手標註；Stellar Verdict API 未通）。  
5. **無**自動隔離／停用帳號／防火牆變更。  
6. **無** Stellar case webhook；靠 poll。  
7. Decision 規則／知識仍偏 MSSP 現況（WildFire／BIOC／blocked），不是規格寫的「僅 Credential Dumping + Suspicious PowerShell」兩類 MVP。  
8. 路徑 C：優先值班體驗，**暫緩** Golden Dataset／一致率驗收當主 KPI。
9. Tenant 管理目前是 JSON registry + CLI，尚無 Web 管理 UI。
10. `tenant-backfill` 只補 SQLite metadata；舊 Jira 若沒有 tenant label，
    不會納入 label-scoped historical MTTR，需另行 Jira label migration。

---

## 10. 建議規格書應怎麼改寫（章節級）

| 原 SDP 章節意圖 | 改寫成 |
|-----------------|--------|
| 產品定位 | Stellar↔Jira 同步平台 + 嵌入式 Decision Intelligence |
| MVP 事件類型 | Stellar 上實際 Critical/High 案件（含 Malware／BIOC／Behavioral Threat 等），不以兩種攻擊技巧為限 |
| 資料來源 | **僅 Stellar Cyber（poll）**；Cortex 僅透過已進 Stellar 的告警間接存在 |
| 架構圖 | 以本文件 §2 為準 |
| MVP 輸出決策 | escalation / playbook / notify_* / isolate_host(advisory) / labels；classification 標為**可選／後期／依赖標註** |
| Ingestion API | 改為「Poll Stellar Cases API」 |
| Normalizer | 降級為「使用 Stellar 既有 case/alert 結構 + 內部 helpers」 |
| AI Analysis Service | 改為「SOC Notify LLM（advisory）」 |
| Human Review Gate | 改為「Jira 值班覆核 + Decision comment checklist」 |
| Jira 整合 | 雙向 Status、建票、mirror、notify；Decision 以 labels+comment 為主 |
| Decision Dataset | 保留為**後期目標**；標明標註來源缺口 |
| 驗收指標 | 同步成功率、建票正確、Decision 不阻塞建票、值班評論可用性；**拿掉**分類一致率／Golden Set 作為短期必達 |
| 12 週計畫 | 改為「在已上線同步上增量強化 Decision／規則／資產／值班 UX」 |

---

## 11. 範例案型（實際）

| Stellar ticket_id | 重點 |
|-------------------|------|
| 1220 | WildFire + Persistence BIOC；有 Cortex case_id → **略過 Decision**（閘門預設） |
| 1222 | Behavioral Threat；有 Cortex case_id → **略過 Decision** |
| 1214 | Critical BIOC「Known service display name…」；**無** Cortex case_id → **跑 Decision**（Stellar 升 case 代表例） |

---

## 12. 相關文件

- 同步權威：`docs/CURRENT_RUNTIME.md`  
- Decision 操作：`docs/DECISION_LAYER.md`  
- 維運：`docs/MAINTENANCE.md`  
- Agent 指引：`AGENTS.md`  
- 實作規格基線：repo 根目錄 `Security_Decision_Platform_MVP_Spec_v1.0.md`
