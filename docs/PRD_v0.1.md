> **AI AGENTS — DO NOT READ FOR RUNTIME (Tier 3).**  
> **~700 lines** future dual-portal PRD; most sections **not implemented**.  
> Shipped boss demo: [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md). Sync: [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md).  
> Open **only** if user explicitly asks for full PRD / long-term product design.

# PRD v0.1 — Stellar SOC Platform（多租戶 MDR 平台）

- **文件版本：** v0.1  
- **文件狀態：** Draft（產品規格基線，**多數未實作**；勿與 xMDR Demo 混淆）  
- **文件日期：** 2026-07-23（規格草稿；**未實作**）  
- **已上線產品：** 見 [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md)（單一 xMDR Web，非本 PRD 雙 Portal）  
- **適用倉庫：** `stellar-jira`（產品演進中；由 Stellar↔Jira middleware 轉型為自有平台）  
- **技術/runtime 參考：** `docs/CURRENT_RUNTIME.md`（現行同步行為）、`env.example`  
- **取代關係：** 本 PRD 為 **新產品** 規格；`Security_Decision_Platform_MVP_Spec_v1.0.md` 描述已上線的 Jira 中介層，兩者並存至實作完成遷移

---

## 1. 背景與前提

### 1.1 團隊與營運現況

- 新團隊，**尚無真實付費客戶**在 production 使用。  
- **不依賴 Jira 營運**；可將 Jira 從主系統降級為可選 adapter（或完全關閉）。  
- 現有 repo 已具備：Stellar poll、multi-tenant registry、Decision Layer、Email/LINE 通知、case archive、automation cycle。  
- 本 PRD 定義在既有引擎上長出 **雙入口 Web 平台** 的 MVP。

### 1.2 產品一句話

> **Stellar 事件進平台 → SOC 內部自動開票與辦案 → 客戶以 Email 協作調查，並透過 Client Portal 查看 Overview、案件（含受影響主機/IP）、系統設定。**

### 1.3 非目標（v0.1 明確不做）

- 客戶在系統內辦案、分派、手動結案  
- 可拖拽表單設計器  
- 取代 Stellar / 客戶端 EDR 主控台  
- 自動隔離、封鎖 IP、刪檔等高風險自動處置  
- 完整 Human Review Gate / TP-FP 分類驗收平台  
- Inbound email 自動結案（可列 Phase 2；v0.1 以 SOC 手動結案為主）  
- 客戶月報下載、API key、白標（後期）

---

## 2. 產品定位

### 2.1 系統角色

| 元件 | 角色 |
|------|------|
| **Stellar Cyber** | 事件來源（Cases API poll） |
| **Platform Backend** | 同步、開票、通知、狀態、資料儲存 |
| **SOC Portal** | 內部值班辦案（全 tenant） |
| **Client Portal** | 客戶唯讀/有限設定（單 tenant） |
| **Email（soc@jjnetservice.com.tw）** | 客戶協作主通道：收告警、回信、結案請求 |

### 2.2 與現有 middleware 的關係

```text
現有（過渡）                    目標（本 PRD）
─────────────────────────────────────────────────
Stellar poll                  →  保留
Tenant registry               →  保留（可遷至 DB，registry 為種子）
Decision Layer                →  保留（SOC 可見；客戶不可見）
Jira create/mirror/writeback  →  替換為 Platform Ticket + Stellar writeback
SOC Email/LINE notify         →  保留並綁 Platform Ticket
incident_jira 表              →  演進為 tickets / case_links
```

---

## 3. 使用者與角色（RBAC）

### 3.1 角色定義

| 角色 ID | 所屬 | 說明 |
|---------|------|------|
| `platform_admin` | Platform（SOC 組織） | 平台設定、tenant 生命週期、SOC 使用者管理 |
| `soc_analyst` | Platform | 全 tenant 辦案：開票後操作、通知、結案 |
| `soc_viewer` | Platform | 全 tenant 唯讀 |
| `tenant_admin` | Tenant（客戶） | 自家 Overview、案件、**系統設定**（含邀請同 tenant 使用者） |
| `tenant_viewer` | Tenant | 自家 Overview、案件唯讀；**不可進系統設定** |

### 3.2 權限矩陣（MVP）

| 能力 | platform_admin | soc_analyst | soc_viewer | tenant_admin | tenant_viewer |
|------|:--------------:|:-----------:|:----------:|:------------:|:-------------:|
| SOC Overview（全 tenant） | ✅ | ✅ | ✅ | — | — |
| Client Overview（自家） | ✅ | ✅ | ✅ | ✅ | ✅ |
| 案件檢視（SOC 完整欄位） | ✅ | ✅ | ✅ | — | — |
| 案件檢視（客戶對外欄位） | ✅ | ✅ | ✅ | ✅ | ✅ |
| 受影響主機/IP | ✅ | ✅ | ✅ | ✅ | ✅ |
| 工單分派 / 狀態變更 / 結案 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 發送 / 重寄客戶通知 | ✅ | ✅ | ❌ | ❌ | ❌ |
| SOC 內部備註 | ✅ | ✅ | 唯讀 | ❌ | ❌ |
| Quarantine 工作台 | ✅ | ✅ | 唯讀 | ❌ | ❌ |
| Tenant / SOC 使用者管理 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 客戶系統設定 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 我的帳號（密碼、2FA） | ✅ | ✅ | ✅ | ✅ | ✅ |

### 3.3 Tenant 資料隔離（強制）

- 所有 Client API **必須**在後端依 `user.tenant_source_id`（或 memberships）過濾，**禁止**信任 query 參數切 tenant。  
- SOC 角色 `tenant_scope = *`；客戶角色 `tenant_scope = [單一 source_id]`。  
- 審計日誌記錄：使用者 ID、動作、資源、tenant、時間戳。

### 3.4 認證與 2FA

| 項目 | MVP 規格 |
|------|----------|
| 登入 | Email + 密碼 |
| Session | HTTP-only cookie 或 Bearer JWT（實作時二選一，文件不綁死） |
| 2FA | TOTP（Google Authenticator 等） |
| 2FA 強制對象 | `platform_admin`、`soc_analyst`、`tenant_admin` |
| `tenant_viewer` | 建議強制 2FA；若趕 MVP 可設為「首次登入後強制綁定」 |
| 密碼重設 | Email 重設連結（Phase 1 可簡化為 admin 重設） |
| 未來擴充 | OIDC / Azure AD（Phase 3+，不擋 MVP） |

---

## 4. 端到端業務流程

### 4.1 主流程（Happy Path）

```text
1. Stellar 產生 / 更新 case（severity 符合 tenant policy，預設 Critical/High）
2. Platform poll → tenant classify →（可選）Decision Layer
3. 新 case 且未開票 → 自動建立 Platform Ticket（僅 SOC 可見內部欄位）
4. 事件通知
   ├─ 預設：自動寄送客戶 Email（+ 可選 LINE，沿用現有 notify）
   └─ 可選：值班在 SOC UI 手動點「發送通知」
5. 客戶收到信 → 依指引調查（郵件、電話等，主要在系統外）
6. 客戶可登入 Client Portal 查看 Overview、案件詳情（含受影響主機/IP）
7. 結案（三條路並存）
   ├─ 客戶回信 soc@jjnetservice.com.tw 表示可結案
   ├─ 客戶另通知 SOC（電話 / LINE / 新信）請結案
   └─ SOC 在 Ticket System 手動結案
8. 結案後：Ticket → Resolved/Closed；可選 Stellar status writeback
9. 可選：寄送結案確認信給客戶
```

### 4.2 通知模式

| 模式 | 行為 | 預設 |
|------|------|------|
| **自動** | 開票成功後立即寄客戶通知 | **MVP 預設** |
| **手動** | 開票後狀態維持待通知，SOC 點擊後才寄 | 可 per-tenant 或全域開關 |

通知信 **必須** 包含：

- `From` / `Reply-To`：`soc@jjnetservice.com.tw`（或等價設定）  
- `Subject` 含平台案件編號：`[XSOC-{customer_code}-{YYMMDD}-{seq}]`  
- 內文：事件摘要、嚴重度、偵測時間、受影響主機/IP（精簡）、聯絡方式  

### 4.3 結案規則（v0.1）

| 路徑 | v0.1 行為 |
|------|-----------|
| 客戶回信 soc@ | **記錄為待辦**；SOC 確認後手動結案（不自動結案） |
| 客戶口頭/LINE 請求 | SOC 手動結案 |
| SOC 判定可結 | SOC 手動結案 |

Inbound email 解析與半自動結案列 **Phase 2**。

---

## 5. 雙入口功能規格

### 5.1 SOC Portal（內部）

#### 5.1.1 導覽結構（MVP）

1. **Overview（營運）** — 全 tenant 聚合  
2. **Tickets** — 工單列表與詳情  
3. **Quarantine** — unknown / mismatch tenant cases  
4. **Tenants** — registry 檢視與基本管理（platform_admin）  
5. **Users** — SOC 使用者（platform_admin）  
6. **Settings** — 平台級通知、自動/手動通知開關  

#### 5.1.2 Overview（SOC）

| 區塊 | 內容 |
|------|------|
| 摘要卡 | 今日新票、開放中、Critical/High、待客戶、quarantine 數 |
| 依 tenant 分布 | 各 tenant 開放案件數、嚴重度 |
| 同步健康 | 最後一輪 automation 時間、deferred 佇列、最近錯誤筆數 |
| 最近案件 | 全平台最近 N 筆 |

#### 5.1.3 Ticket 列表

| 欄位 | 說明 |
|------|------|
| 案件編號 | `XSOC-…` |
| Tenant | source_id / tenant_name |
| 標題 | 告警名稱摘要 |
| 嚴重度 | Critical / High / … |
| 內部狀態 | 見 §6.2 |
| Assignee | 值班人員 |
| Stellar case ID | 內部參考 |
| 建立 / 更新時間 | — |

篩選：tenant、severity、status、assignee、日期範圍、關鍵字。

#### 5.1.4 Ticket 詳情

| 區塊 | 內容 |
|------|------|
| 基本資訊 | 編號、tenant、嚴重度、內部狀態、assignee、Stellar 連結 |
| 事件內容 | 完整 description（`stellar_case_detail_lines` 同級） |
| 受影響資產 | 主機、IP、帳號、process（SOC 完整） |
| Decision | action、escalation、playbook、labels（若有） |
| 時間軸 | 開票、通知、狀態變更、內部備註、客戶回信（Phase 2） |
| 操作 | 分派、改狀態、發送/重寄通知、新增內部備註、結案 |

#### 5.1.5 Ticket 操作（MVP）

| 操作 | 說明 |
|------|------|
| Assign | 指定 SOC 分析師 |
| Change status | 內部狀態機轉換 |
| Notify customer | 手動或重寄客戶通知 |
| Internal note | 僅 SOC 可見 |
| Resolve / Close | 結案；觸發 Stellar writeback（可設定） |

---

### 5.2 Client Portal（客戶）— 僅三大項

客戶 **不** 看到 SOC 工單操作介面、內部備註、Decision 全文、完整 raw alerts。

#### 5.2.1 Overview

**資料範圍：** 僅登入使用者所屬 tenant。

| 區塊 | MVP 內容 |
|------|----------|
| 摘要卡 | 開放中案件、本月新案、Critical/High 數 |
| 狀態分布 | 已通報 / 調查中 / 待貴司配合 / 已結案 |
| 趨勢 | 近 7 或 30 天案件數（簡單長條或折線） |
| 最近案件 | 最近 5–10 筆（編號、標題、嚴重度、狀態、時間） |

**v0.1 不做：** 受影響主機排行、MTTR 進階分析、自訂 widget。

#### 5.2.2 案件檢視

**列表頁**

| 欄位 | 說明 |
|------|------|
| 案件編號 | `XSOC-…` |
| 標題 | 告警名稱 |
| 嚴重度 | — |
| 對外狀態 | 見 §6.3 |
| 偵測時間 | — |
| 更新時間 | — |

篩選：日期、嚴重度、對外狀態。

**詳情頁**

| 區塊 | 客戶可見 |
|------|----------|
| 基本資訊 | 案件編號、標題、嚴重度、對外狀態、偵測時間 |
| **受影響主機 / IP** | **表格：主機名稱、IP（見 §7）** |
| 事件摘要 | 告警名稱、精簡說明（非完整 raw alerts） |
| 聯絡 SOC | 說明可回信 `soc@jjnetservice.com.tw`；顯示案件編號以便引用 |

**客戶不可見：** 內部 assignee、Decision、process/檔案路徑、MITRE 細節、SOC 備註、完整 alerts、結案按鈕。

**v0.1 不做：** 客戶留言、附件上傳、線上結案。

#### 5.2.3 系統設定

| 子頁 | 權限 | MVP 內容 |
|------|------|----------|
| **通知收件人** | tenant_admin | 告警 Email 列表（增刪改） |
| **聯絡人** | tenant_admin | 主要聯絡人姓名、電話 |
| **使用者管理** | tenant_admin | 邀請/停用同 tenant 的 `tenant_admin` / `tenant_viewer` |
| **我的帳號** | 所有客戶角色 | 改密碼、綁定/管理 2FA |
| **組織資訊** | 所有客戶角色 | 公司名稱、tenant_name（**唯讀**，來自 registry） |

**v0.1 不做：** 自訂通知模板、API key、logo 白標、IP allowlist（後期可放在此處）。

---

## 6. 狀態機

### 6.1 內部狀態（SOC Ticket）

| 狀態 ID | 顯示名稱 | 說明 |
|---------|----------|------|
| `new` | New | 已開票，尚未通知客戶（手動通知模式） |
| `notified` | Notified | 已發送客戶通知 |
| `investigating` | Investigating | SOC 調查中 |
| `pending_customer` | Pending Customer | 待客戶回覆或配合 |
| `resolved` | Resolved | 已結案 |
| `closed` | Closed | 已關閉（終態） |

建議轉換（簡化）：

```text
new → notified → investigating ↔ pending_customer → resolved → closed
```

自動通知模式：開票後可直接 `notified`。

### 6.2 對外狀態（Client 映射）

| 內部狀態 | 客戶看到 |
|----------|----------|
| `new`, `notified` | **已通報** |
| `investigating` | **調查中** |
| `pending_customer` | **待貴司配合** |
| `resolved`, `closed` | **已結案** |

API 層 **只回傳** `client_status` 枚舉，不回傳內部狀態給客戶角色。

### 6.3 Stellar 同步

- Inbound：Stellar case 變更 → 更新 Platform Ticket 欄位（severity、summary 等）。  
- Outbound：SOC 結案 → Stellar status writeback（沿用現有映射概念，目標改為 Platform Ticket ID）。  
- 衝突規則：參考 `docs/CURRENT_RUNTIME.md`（Stellar 較新時 inbound 優先等）。

---

## 7. 受影響主機 / IP（客戶可見）

### 7.1 資料來源

Stellar case bundle：`observables.observables.host[]`，每筆含 `hostname`、`ip`。

與現有程式對齊（`app/stellar/jira_draft.py` `_host_line`）；實作時抽成共用：

```text
extract_affected_hosts(bundle) -> list[{hostname: str|None, ip: str|None}]
```

### 7.2 客戶 UI 呈現

- 區塊標題：**受影響主機 / IP**  
- 表格欄位：**主機名稱** | **IP 位址**  
- 僅 hostname 或僅 IP 時另一欄顯示 `—`  
- 去重、上限 **20 筆**；超出顯示「另有 N 筆…」  
- 無資料：顯示「尚無主機／IP 資訊」

### 7.3 客戶 API 片段

```json
"affected_hosts": [
  { "hostname": "WORKSTATION-01", "ip": "192.168.1.50" },
  { "hostname": null, "ip": "10.0.0.12" }
]
```

### 7.4 仍對客戶隱藏（MVP）

| 類型 | SOC | 客戶 |
|------|:---:|:----:|
| 主機 / IP | ✅ | ✅ |
| 受影響帳號 | ✅ | 後加 |
| Process / 檔案路徑 | ✅ | ❌ |
| 完整 alerts | ✅ | ❌ |

### 7.5 後期可選

- per-tenant 設定：「詳情僅顯示主機名稱、隱藏 IP」  
- Overview：本週受影響主機數（去重）

---

## 8. Multi-tenant 模型

### 8.1 概念層級

```text
Organization（JJNET SOC 平台）
├── SOC Users（platform scope）
└── Tenants
      ├── jjnet（customer_code: JJNET）
      ├── jjnet-edr（customer_code: JJEDR）
      └── …
            └── Tenant Users
```

### 8.2 Tenant 屬性（對齊 registry）

| 欄位 | 說明 |
|------|------|
| `source_id` | 穩定識別；API、label 用 |
| `tenant_id` | Stellar `cust_id`（權威） |
| `tenant_name` | Stellar 顯示名；交叉驗證 |
| `customer_code` | 案件編號維度 |
| `enabled` / `sync_enabled` | 同步開關 |
| `allowed_severities` | 預設 `Critical, High` |
| `notify_emails` | 客戶通知收件人（可遷出 JSON） |

### 8.3 分類與 Quarantine

沿用現行嚴格分類：

- Unknown `cust_id`、name mismatch、disabled tenant → quarantine，不開票。  
- SOC Portal 提供 quarantine 列表與處理指引（v0.1 可唯讀）。

---

## 9. 資料模型（草案）

### 9.1 新資料庫

建議 **獨立** `data/platform.db`（與 `stellar_sync_state.sqlite` 分離），避免 sync lock 與資安邊界混雜。

### 9.2 核心表

#### `users`

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | UUID | PK |
| email | TEXT UNIQUE | 登入帳號 |
| password_hash | TEXT | — |
| role | ENUM | 見 §3.1 |
| tenant_source_id | TEXT NULL | 客戶角色必填；SOC 為 NULL |
| totp_secret | TEXT NULL | 加密儲存 |
| totp_enabled | BOOL | — |
| is_active | BOOL | — |
| created_at | TIMESTAMP | — |

#### `tickets`

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | UUID | PK |
| ticket_no | TEXT UNIQUE | XSOC-… |
| tenant_source_id | TEXT | FK → tenant |
| stellar_case_id | TEXT | Stellar `_id` |
| severity | TEXT | — |
| title | TEXT | — |
| description_text | TEXT | SOC 完整內文 |
| client_summary | TEXT | 客戶精簡摘要 |
| status | TEXT | 內部狀態 §6.1 |
| assignee_user_id | UUID NULL | — |
| stellar_status | TEXT | 鏡像 |
| notified_at | TIMESTAMP NULL | — |
| resolved_at | TIMESTAMP NULL | — |
| created_at / updated_at | TIMESTAMP | — |

唯一約束：`(tenant_source_id, stellar_case_id)` 或全域 `(stellar_case_id)` 依 poll source 設計。

#### `ticket_events`（時間軸）

| 欄位 | 說明 |
|------|------|
| ticket_id | FK |
| event_type | `created`, `status_changed`, `notified`, `note`, `assigned`, `email_inbound`, … |
| actor_user_id | NULL 表系統 |
| payload_json | 變更細節 |
| created_at | — |

#### `ticket_snapshots`

| 欄位 | 說明 |
|------|------|
| ticket_id | FK |
| snapshot_ref | 指向 `data/case_archive/` 或內嵌 JSON |
| captured_at | — |

受影響主機/IP **建議開票時解析寫入** `tickets.affected_hosts_json` 以加速客戶列表；詳情可從 snapshot 重算。

#### `tenant_settings`

| 欄位 | 說明 |
|------|------|
| tenant_source_id | PK |
| notify_emails_json | 收件人列表 |
| contact_name / contact_phone | 聯絡人 |
| notify_mode | `auto` / `manual` |
| updated_at | — |

#### `audit_log`

| 欄位 | 說明 |
|------|------|
| user_id | — |
| action | — |
| resource_type / resource_id | — |
| tenant_source_id | NULL |
| ip_address | — |
| created_at | — |

### 9.3 與現有 SQLite 的銜接

| 現有 | 演進 |
|------|------|
| `incident_jira` | `tickets` + `stellar_case_id`；過渡期可雙寫或 migration script |
| `tenant_case_quarantine` | 保留於 sync DB 或複製視圖至 platform |
| `decision_events` | 保留；SOC API join 查詢 |
| `case_archive/` | 保留；開票時 archive milestone |

---

## 10. API 規格（概要）

### 10.1 路由前綴

| 前綴 | 對象 | 說明 |
|------|------|------|
| `/v1/auth/*` | 全體 | 登入、登出、2FA、refresh |
| `/v1/soc/*` | SOC 角色 | 完整 ticket、quarantine、營運 |
| `/v1/client/*` | 客戶角色 | 強制 tenant scope + 欄位遮罩 |
| `/v1/webhooks/*` | 系統 | 既有 line；Phase 2 加 inbound-email |
| `/health` | 監控 | 沿用 |

### 10.2 Client API（MVP）

| Method | Path | 說明 |
|--------|------|------|
| GET | `/v1/client/overview` | Overview 聚合 |
| GET | `/v1/client/cases` | 案件列表（分頁、篩選） |
| GET | `/v1/client/cases/{id}` | 案件詳情含 `affected_hosts` |
| GET | `/v1/client/settings` | 讀取 tenant 設定 |
| PUT | `/v1/client/settings/notifications` | 更新通知收件人 |
| PUT | `/v1/client/settings/contact` | 更新聯絡人 |
| GET | `/v1/client/users` | 列同 tenant 使用者 |
| POST | `/v1/client/users` | 邀請使用者 |
| PATCH | `/v1/client/users/{id}` | 停用/改角色 |

### 10.3 SOC API（MVP 摘錄）

| Method | Path | 說明 |
|--------|------|------|
| GET | `/v1/soc/overview` | 全 tenant 營運總覽 |
| GET | `/v1/soc/tickets` | 工單列表 |
| GET | `/v1/soc/tickets/{id}` | 工單詳情（完整） |
| PATCH | `/v1/soc/tickets/{id}` | 更新狀態、assignee |
| POST | `/v1/soc/tickets/{id}/notes` | 內部備註 |
| POST | `/v1/soc/tickets/{id}/notify` | 發送/重寄客戶通知 |
| POST | `/v1/soc/tickets/{id}/resolve` | 結案 |
| GET | `/v1/soc/quarantine` | Quarantine 列表 |

### 10.4 DTO 原則

- `ClientCaseDTO`：僅含 §5.2.2 允許欄位 + `affected_hosts` + `client_status`。  
- `SocTicketDTO`：完整欄位 + Decision + 內部備註。  
- 同一 `tickets` 表，不同 role 走不同 serializer（**禁止**客戶 API 回傳內部欄位）。

---

## 11. 前端（概要）

### 11.1 技術建議

- React + Vite + TypeScript（或團隊熟悉之框架）  
- 單一 SPA，依 `user.role` 渲染不同 sidebar  
- TanStack Query 打 API；OpenAPI 生成型別  

### 11.2 導覽

**SOC 登入後**

- Overview → Tickets → Quarantine → Tenants → Users → Settings  

**客戶登入後（僅三項）**

- Overview → 案件檢視 → 系統設定  

### 11.3 部署

- 靜態檔由 FastAPI `StaticFiles` 掛載，或 Nginx 分離  
- `stellar-jira-api.service`：`uvicorn app.main:app`  
- `stellar-jira-automation.service`：維持 poll loop（與 API 分離）

---

## 12. 重用與替換（技術對照）

| 模組 | 動作 |
|------|------|
| `app/stellar_sync/runner.py` | 改：建 Platform Ticket 取代 Jira create |
| `app/notify/ticket_created.py` | 改：綁 `ticket_no`、per-tenant 收件人 |
| `app/stellar/jira_draft.py` | 重用：`stellar_case_detail_lines`、抽出 `extract_affected_hosts` |
| `app/decision/*` | 保留；結果寫入 ticket / decision_events |
| `app/jira/*` | v0.1 關閉；保留程式碼作 optional adapter |
| `app/stellar/writeback.py` | 改：由 Platform 結案觸發 |
| `config/stellar_tenants.json` | 種子資料；長期遷 `tenant_settings` |

---

## 13. 實作分期

| 階段 | 交付 | 驗收標準 |
|------|------|----------|
| **P0** | Auth、RBAC、TOTP、users 表 | SOC/客戶可登入；角色正確 |
| **P1** | Stellar poll → 自動開票 → 自動 Email；SOC Ticket 列表/詳情/結案 | 無 Jira 亦可跑通一輪 |
| **P2** | Client Overview + 案件檢視（含主機/IP） | tenant 隔離測試通過 |
| **P3** | Client 系統設定 + SOC Overview/Quarantine | tenant_admin 可改收件人 |
| **P4** | Inbound email、Stellar writeback 強化、報表 | 依優先級排入 |

**內部 Demo 門檻（P2 完成）：** Stellar staging case → 自動開票與通知 → SOC 結案 → 客戶登入看見案件與主機/IP。

---

## 14. 非功能性需求

| 類別 | MVP 目標 |
|------|----------|
| 可用性 | API + automation 分離部署；單一節點 acceptable |
| 安全 | HTTPS、密碼 hash（bcrypt/argon2）、TOTP、tenant 隔離測試、audit log |
| 效能 | 客戶案件列表 < 2s（1000 筆內）；詳情含 snapshot 解析 < 3s |
| 可維運 | `/health`、`/health/ready`；結構化 log |
| 相容 | 沿用 `.env` 大部分 Stellar/notify 設定 |

---

## 15. 風險與假設

| 項目 | 說明 |
|------|------|
| `soc@jjnetservice.com.tw` inbound | v0.1 假設尚未自動解析；結案靠 SOC 手動 |
| 信箱/Resend | 出站沿用 Resend/SMTP；inbound 待 P4 選型 |
| 無真實客戶 | 可用 jjnet registry + staging Stellar 驗證 |
| Jira 程式殘留 | 需明確 `JIRA_ENABLED=false` 避免誤開 |
| 客戶看 IP | 已確認為需求；若未來要隱藏需 per-tenant 開關 |

---

## 16. 開放問題（實作前確認）

| # | 問題 | 建議預設 |
|---|------|----------|
| 1 | Critical 是否一律自動通知、其餘手動？ | 全部自動 |
| 2 | 客戶 `tenant_viewer` 是否強制 2FA？ | 是 |
| 3 | 結案是否一律 writeback Stellar？ | 是 |
| 4 | 案件編號是否沿用 `XSOC-{customer_code}-{YYMMDD}-{seq}`？ | 是 |
| 5 | 前端是否同一網域 `/` SOC、`/client` 客戶？ | 同一 SPA 依 role 分流 |

---

## 17. 詞彙表

| 詞彙 | 定義 |
|------|------|
| **Ticket** | 平台內部工單（取代 Jira issue） |
| **Case** | Stellar Cyber case |
| **Tenant** | 客戶組織單位，對應 registry `source_id` |
| **對外狀態** | 客戶看到的四態：已通報/調查中/待貴司配合/已結案 |
| **Quarantine** | 無法歸屬 tenant 的 Stellar case，不開票 |

---

## 18. 修訂紀錄

| 版本 | 日期 | 說明 |
|------|------|------|
| v0.1 | 2026-07-23 | 初版：雙入口、SOC 開票流程、客戶三模組、RBAC/2FA、主機/IP 可見 |
| v0.1.1 | 2026-07-23 | P0 實作：platform auth API、users DB、TOTP、CLI |

---

## 附錄 A — 客戶案件詳情 Wireframe（文字）

```text
┌─────────────────────────────────────────────────────────┐
│ 案件編號: XSOC-JJNET-260723-001          狀態: 調查中    │
│ 嚴重度: High                         偵測: 2026-07-23 … │
├─────────────────────────────────────────────────────────┤
│ 告警名稱                                                 │
│ Palo Alto Networks Cortex XDR: …                        │
├─────────────────────────────────────────────────────────┤
│ 受影響主機 / IP                                          │
│ ┌──────────────────┬─────────────────┐                  │
│ │ 主機名稱          │ IP 位址          │                  │
│ ├──────────────────┼─────────────────┤                  │
│ │ WORKSTATION-01   │ 192.168.1.50    │                  │
│ │ SERVER-DC-02     │ 10.10.1.5       │                  │
│ └──────────────────┴─────────────────┘                  │
├─────────────────────────────────────────────────────────┤
│ 事件摘要                                                 │
│ （精簡說明文字）                                          │
├─────────────────────────────────────────────────────────┤
│ 如需結案或提供資訊，請回信 soc@jjnetservice.com.tw         │
│ 並註明案件編號 XSOC-JJNET-260723-001                     │
└─────────────────────────────────────────────────────────┘
```

## 附錄 B — 環境變數（新增草案）

```env
# Platform（新增，實作時併入 env.example）
PLATFORM_DB_PATH=data/platform.db
PLATFORM_SECRET_KEY=change-me
PLATFORM_SESSION_TTL_HOURS=24
PLATFORM_REQUIRE_TOTP=true

# 通知
SOC_NOTIFY_FROM=soc@jjnetservice.com.tw
SOC_REPLY_TO=soc@jjnetservice.com.tw

# 關閉 Jira（綠地預設）
JIRA_ENABLED=false
```

---

*本文件為產品規格；runtime 同步細節以實作完成後更新之 `docs/CURRENT_RUNTIME.md` 為準。*
