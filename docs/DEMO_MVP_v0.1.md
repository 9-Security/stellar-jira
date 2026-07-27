> **AI AGENTS — Tier 2.** Read when task touches **xMDR Web** (`web/`, `app/platform/`, `app/demo/`, Tunnel).  
> Stellar↔Jira automation: use `CURRENT_RUNTIME.md` — not this file.

# Demo MVP v0.1 — 老闆預覽版（xMDR）

- **文件版本：** v0.6  
- **文件狀態：** **已上線（老闆 Demo 可用）**  
- **文件日期：** 2026-07-27  
- **對外網址：** https://xmdr.nine-security.com  
- **完整規格：** [`PRD_v0.1.md`](PRD_v0.1.md)（仍有效，但 **本階段不實作** 其中大部分）

---

## 0. 目前狀態摘要（2026-07-27）

| 項目 | 狀態 |
|------|------|
| Web UI + API | ✅ 已部署（`stellar-soc-api.service` + `web/dist`） |
| Cloudflare Tunnel | ✅ `xmdr.nine-security.com` → `127.0.0.1:8000`（見 [`CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md)） |
| 登入 / per-user 2FA | ✅ |
| 儀表板（真實資料 + AIxSOC 即時） | ✅ P1/P2 + **tenant 範圍篩選**（見 §4.2、§5.6） |
| 案件中心（唯讀） | ✅ XSOC 案件編號；列表／詳情依 tenant 隔離 |
| 帳號管理 | ✅ `platform_admin` + `tenant_admin`（tenant 範圍內） |
| Multi-tenant 資料隔離 | ✅ 儀表板／列表／詳情／帳號管理；live + sync 雙路徑 |
| UI：Tenant + 個人名片 | ✅ 右上角 Tenant 選單（MSSP＝全部）+ 個人名片登出 |
| CyCraft EDR 整合器 | ✅ Tenant 隔離設定 UI（`+` / 儲存 / Test）；DB 加密金鑰；multi-tenant poller |
| 對外品牌 | ✅ xMDR UI 僅 **AIxSOC**（不顯示 Stellar Cyber 產品名） |
| 資安強化（工程面） | ✅ Cookie session、rate limit、關閉 `/docs` 等（§5.7） |
| Cloudflare Access | ⏸ 未實作（可手動於 Cloudflare 後台加） |
| Alerts 儀表板（P3/P4） | ⏸ 延後 |
| Users/Assets 趨勢（P5） | ⏸ 不做 |

**常駐服務（GCP VM）：**

```text
stellar-soc-api.service           # FastAPI + SPA（127.0.0.1:8000）— /v1/settings/* 等
cloudflared-stellar-soc.service   # Tunnel → xmdr.nine-security.com
ticket-api-stellar-jira.service   # Stellar↔Jira 自動化
cycraft-xcockpit-connector.service   # 選用：CyCraft multi-tenant poller
```

**變更後需執行：** `./Tools/run web-build`（若改前端）→ `sudo systemctl restart stellar-soc-api.service`

---

## 1. 目標（這一階段只做什麼）

給老闆看 **可登入的 Web 基本版**，包含：

| # | 畫面 | 說明 |
|---|------|------|
| 1 | **登入** | Email + 密碼；依帳號 **個別** 決定是否要走 2FA（見 §3.4） |
| 2 | **數據儀表板** | **AIxSOC 即時**（後端 Stellar Cases API，`source=auto`）+ sync DB fallback；時間窗可切 |
| 3 | **案件管理中心** | **真實案件**列表 + 詳情；編號以 **XSOC-*** 為主 |
| 4 | **設定中心 → 帳號管理** | 新增 / 停用帳號；管理各帳號是否啟用 2FA |

**刻意不做（延後）：**

- Platform Ticket 取代 Jira 建票  
- 客戶 Portal（客戶自己登入看案）  
- 通知收件人、tenant 業務設定、改 `.env`  
- Quarantine 工作台、tenant registry UI、報表下載  
- 案件在 UI 內辦案 / 結案（仍唯讀）  

---

## 2. 已確認決策（2026-07-24）

| # | 決策 |
|---|------|
| 1 | **老闆帳號 Demo 可不綁 2FA**；但系統要有 **設定中心 → 帳號管理**，可替各帳號開關 2FA |
| 2 | 儀表板 **以平台即時 Cases 為主**（`source=auto`），API 失敗時 fallback **sync DB** |
| 3 | 案件管理 **sync DB 已建票案件**為完整詳情；即時未建票者顯示「未建票」 |
| 4 | 案件編號 UI 顯示 **middleware `XSOC-{客戶}-{YYMMDD}-{seq}`**，非 Stellar `_id` |
| 5 | Jira 建票 automation **維持不變**；xMDR 為唯讀展示層 |
| 6 | **MSSP 視角**：Platform 角色右上角 Tenant 下拉，預設「MSSP」= 全部 tenant；選單一 tenant 時儀表板／案件／詳情皆限該 tenant |
| 7 | **Tenant 角色**：強制 `users.tenant_source_id`；不可透過 query 切換其他 tenant（403） |

---

## 3. 與現有系統的關係

```text
現有 automation（不動）
  Stellar poll → Jira 建票 → notify
        ↓
  stellar_sync_state.sqlite + case_archive
  decision_events.middleware_case_id  ← XSOC 案件編號
        ↓（唯讀）
  Demo API + Web UI（xMDR）  ← 老闆看這裡
        ↑
  Stellar Cases API（儀表板即時指標，可選）

platform.db（users、tenant_integrations）  ← 登入 + 帳號管理 + 外部整合器（加密金鑰）
```

| 項目 | Demo 階段 |
|------|-----------|
| Jira 建票 | **維持現狀**，不修改 `runner.py` |
| `.env` | 全域 automation / 平台預設；**整合器 API 金鑰可改存** `platform.db`（UI 加密）或 `VAR__TENANT_SUFFIX` |
| P0 Auth | **已實作**，擴充 per-user 2FA 政策 + 管理 API |
| 案件資料 | `incident_jira` + `CaseSnapshotStore`（與 `/v1/ai-data` 同源） |

---

## 4. 畫面規格

### 4.1 登入頁

- Email / 密碼  
- 若該帳號 `totp_policy=required` 且已綁定 → 第二步 TOTP  
- 若 `totp_policy=off` 或 `optional` 且未綁定 → 密碼即可進（老闆帳號預設 `off`）  

### 4.2 數據儀表板

**資料來源（已實作）：**

| 模式 | 說明 | UI 標示 |
|------|------|---------|
| `source=auto`（預設） | 先打 **Stellar Cases API**，失敗則讀 sync DB | 「AIxSOC 即時」或「AI SOC 同步」 |
| `source=live` | 強制 Stellar Cases API | 「AIxSOC 即時」 |
| `source=sync` | 僅 sync DB（已連 Jira 子集） | 「AI SOC 同步」 |

**時間與指標（P1 + P2，已完成）：**

| 控制項 | 選項 | 說明 |
|--------|------|------|
| Tenant 範圍 | 右上角下拉（Platform） | **MSSP** = 全部；選 `jjnet` 等 = 僅該 tenant（query `tenant=`） |
| 時間範圍 `window` | `12h` / `24h` / `7d` / `all` | 預設 `12h`，對齊 Stellar UI 觀感 |
| 新案基準 `new_basis` | `created` / `modified` | 摘要卡「區間內新案」 |
| 範圍 `scope` | `modified` / `created` | API 篩選用（前端預設 modified） |

**Tenant 範圍顯示：** 標題下方 `資料範圍：JJNET · 資料來源：AIxSOC 即時`（`meta.source=stellar_live` 為內部值；切換 Tenant 會重新載入 API）。

**即時資料的 tenant 過濾：** Stellar Cases API 帶 `tenant_id`（來自 registry）後，再以 `config/stellar_tenants.json` **精確比對** `cust_id` / `tenant_id` / `tenant_name`（禁止子字串，避免 `jjnet` 誤含 `jjnet-edr`）。sync fallback 則在 SQL `incident_jira.tenant_source_id` 過濾。

**畫面區塊：**

| 區塊 | 內容 |
|------|------|
| 摘要卡 | 總案件數、開放中、Critical/High 開放、**區間內新案**（`new_in_window`） |
| 嚴重度分布 | 即時或 sync 聚合 |
| 狀態分布 | 即時或 sync 聚合 |
| ~~Tenant 分布~~ | **已移除**（2026-07-24） |
| 最近案件（最多 50 筆） | **客戶端篩選**：搜尋、建票狀態（已建票/未建票）、嚴重度、狀態 |

**案件編號顯示規則：**

| 情況 | 顯示 |
|------|------|
| 已建票 | `XSOC-JJNET-260724-001`（來自 `decision_events.middleware_case_id`） |
| 舊案無 XSOC | Jira key（例 `AIXSOC-63`） |
| 即時、尚未建票 | **未建票**（不顯示長串 `_id`） |

**API 回應欄位（摘要）：** `summary.new_in_window`、`meta.source` / `meta.window` / `meta.new_basis`；每筆案件含 `case_number`、`case_ref`。

### 4.3 案件管理中心

**列表欄位：** **XSOC 案件編號**（或 Jira key）、標題、tenant、嚴重度、狀態、更新時間。  
**篩選：** 關鍵字、嚴重度；**tenant 範圍**跟隨右上角 Tenant 選單（與儀表板同源）。

**詳情：**

| 區塊 | 內容 |
|------|------|
| 基本資訊 | **案件編號**（XSOC）、標題、嚴重度、狀態、偵測時間、tenant |
| 受影響主機/IP | `observables.observables.host[]` |
| 事件摘要 | `stellar_case_detail_lines` 精簡版 |

**路由：** `/cases/{id}` 支援 `XSOC-*`、`jira_key`、`stellar_case_id`。

### 4.4 設定中心 → 帳號管理

**導覽：** 側欄「設定中心」展開子項「帳號管理」。  
**權限：** `platform_admin`（全 tenant）；`tenant_admin`（僅自家 tenant 的 tenant 角色帳號）。

| 功能 | 說明 |
|------|------|
| 列表 | Email、角色、tenant、2FA 狀態、啟用狀態 |
| 新增帳號 | Email、初始密碼、角色、tenant（若為 tenant 角色） |
| 停用帳號 | 軟刪除 `is_active=false`（不硬刪，保留 audit） |
| **2FA 管理** | 每帳號 `totp_policy`：`off` / `optional` / `required` |
| 重設 2FA | 清除已綁 TOTP secret，強制下次依政策重綁 |
| 我的帳號（可同頁或子頁） | 改自己的密碼；若政策允許可自助綁定 2FA |

**老闆帳號預設：** `totp_policy=off`（登入不用 Authenticator）。  
**其他帳號：** 管理員可在 UI 設為 `required`。

### 4.5 設定中心 → 外部整合器

**路徑：** `/settings/integrations`  
**權限：** `platform_admin` / `tenant_admin`（`tenant_viewer` 不可進設定）；tenant 角色僅自家 `tenant_source_id`。  
**對外品牌：** UI 僅呈現 **AIxSOC**（不顯示 Stellar Cyber 產品名稱）。

**操作流程：**

1. 右上角 **+** → 下拉選 **CyCraft Connector**
2. 填寫 CyCraft 來源（XCockpit API Key、Customer UUID）與 **AIxSOC 匯入端點**（匯入 API Key、Ingest Path；Auth Path 選填）
3. **儲存** → 寫入 `platform.db`（路徑與 Customer Key + **加密** API 金鑰）
4. **Test** → `POST /v1/settings/integrations/{tenant}/cycraft/test`（可用表單內容測試，不必先儲存）

Platform 管理員須先在頂部 Tenant 選單選定 tenant 再新增；每 tenant 僅一組 CyCraft Connector。  
**營運現況：** CyCraft 套用 **jjnet**（JJNET）；`jjnet-edr` 為獨立 tenant（Cortex），與 CyCraft 無關。

| 整合器 | 說明 |
|--------|------|
| **CyCraft EDR** | XCockpit → AIxSOC 匯入 webhook → 平台案件 → 既有 automation poll → Jira |

**與既有 SOC 連線的關係（不重複建第二套 SOC）：**

- 全域 automation 的 API 金鑰用於 **讀取** 平台案件並同步 Jira。
- 整合器表單的「AIxSOC 匯入」欄位是 **CyCraft 專用 webhook**，用於 **寫入** EDR 告警進同一條案件管道。
- Jira 仍以 `stellar_case_id` 去重。若 CyCraft 告警已從其他路徑進平台，又經本 connector 再送一次，才可能重複案件。

**後端與常駐：**

| 項目 | 說明 |
|------|------|
| 服務總開關 | `.env` `CYCRAFT_CONNECTOR_ENABLED=true` |
| Tenant 設定 | UI + `tenant_integrations`；poller 僅處理 `enabled` 且設定完整的 tenant |
| 常駐 | `cycraft-xcockpit-connector.service` 或 `./Tools/run cycraft-poller` |
| 狀態 DB | `data/cycraft_state/{source_id}.sqlite`（每 tenant 獨立） |
| 程式 | `app/integrations/cycraft/`、`app/routers/tenant_settings.py` |
| HTTP 服務 | 變更 API/UI 後重啟 **`stellar-soc-api.service`**（非僅 automation） |

### 4.6 Layout 與 Tenant 切換

| 區塊 | 說明 |
|------|------|
| 側欄 | 品牌、Live 標籤、導覽（儀表板、案件、設定） |
| 右上角 **Tenant** | Platform 角色：pill 下拉，**MSSP**（空值）或單一 tenant；tenant 角色：固定顯示自家 tenant |
| 右上角 **個人名片** | Email、角色、登出（自側欄底部移至此） |
| 記憶 | Platform 選擇的 tenant 存 `localStorage`（`xmdr_tenant_filter`） |

---

## 5. 技術方案

### 5.1 導覽結構（Web）

```text
登入
└─ Layout
     ├─ 側欄：導覽
     ├─ 頂部列（右上）：Tenant 選單 + 個人名片
     ├─ 數據儀表板
     ├─ 案件管理中心
     │    └─ 案件詳情
     └─ 設定中心
          ├─ 帳號管理
          └─ 外部整合器（CyCraft EDR…）
```

### 5.2 後端 API

**案件與儀表板（唯讀，真實資料）**

| Method | Path | 說明 |
|--------|------|------|
| GET | `/v1/demo/tenants` | 當前使用者可見 tenant 列表 |
| GET | `/v1/demo/overview` | 儀表板聚合；query：`window`、`scope`、`new_basis`、`source`、`tenant` |
| GET | `/v1/demo/cases` | 分頁列表（sync DB）；`severity`、`status`、`q`、`tenant` |
| GET | `/v1/demo/cases/{id}` | 詳情；`XSOC-*` / `jira_key` / `stellar_case_id`；query **`tenant`**（Platform 篩選） |

**帳號管理（`platform_admin` / `tenant_admin`）**

| Method | Path | 說明 |
|--------|------|------|
| GET | `/v1/admin/users` | 列表 |
| POST | `/v1/admin/users` | 新增 |
| PATCH | `/v1/admin/users/{id}` | 停用、改角色、`totp_policy` |
| POST | `/v1/admin/users/{id}/totp-reset` | 清除 TOTP 綁定 |

**外部整合器（`platform_admin` / `tenant_admin`）**

| Method | Path | 說明 |
|--------|------|------|
| GET | `/v1/settings/integrations` | 回傳 `data`、`connectors`、`meta.connector_types`；tenant 隔離 |
| PATCH | `/v1/settings/integrations/{tenant_source_id}` | `enabled`、CyCraft 欄位、匯入 path、加密儲存 API keys |
| POST | `/v1/settings/integrations/{tenant_source_id}/cycraft/test` | 連線測試（body 可帶表單值，不必先 PATCH） |

**既有 Auth（調整登入邏輯）**

| Path | 變更 |
|------|------|
| `/v1/auth/login` | 依使用者 `totp_policy` 決定是否要求 TOTP |
| `/v1/auth/totp/*` | 自助綁定（政策非 `off` 時） |

### 5.3 資料模型擴充（`platform.db`）

`users` 表新增：

| 欄位 | 類型 | 說明 |
|------|------|------|
| `totp_policy` | TEXT | `off` \| `optional` \| `required`（預設 `optional`） |

`tenant_integrations` 表（外部整合器）：

| 欄位 | 說明 |
|------|------|
| `tenant_source_id` | PK，對應 registry `source_id` |
| `cycraft_enabled` | 是否啟用 CyCraft Connector |
| `xcockpit_customer_key` | XCockpit Customer UUID |
| `config_json` | JSON：`cycraft.stellar_xdr_ingest_path`、匯入 URL、`secrets_enc`（加密金鑰）等 |
| `updated_at` / `updated_by_user_id` | 審計 |

Tenant 設定存取：`app/platform/tenant_scope.py`（`tenant_admin` 僅能 PATCH 自家 tenant）。

登入規則：

| totp_policy | totp_enabled | 行為 |
|-------------|--------------|------|
| `off` | — | 僅密碼 |
| `optional` | false | 僅密碼 |
| `optional` | true | 密碼 + TOTP |
| `required` | false | 密碼登入後僅能進 TOTP 設定，完成前限制其他 API |
| `required` | true | 密碼 + TOTP |

### 5.4 設定儲存原則

| 類型 | 存放 | xMDR UI |
|------|------|---------|
| 全域 automation（`STELLAR_API_KEY`、Jira 等） | `.env` | ❌ |
| 整合器 per-tenant 金鑰 | `platform.db` `tenant_integrations.config_json.secrets_enc`（加密）或 `.env` `VAR__SUFFIX` | ✅ 外部整合器 |
| 整合器非機密（ingest path、Customer UUID） | `platform.db` `tenant_integrations` | ✅ 外部整合器 |
| 平台使用者 / 2FA 政策 | `platform.db` `users` | ✅ 帳號管理 |
| 案件與儀表板 | sync SQLite + archive | 唯讀 |

### 5.5 前端

- React + Vite + TypeScript；品牌 **xMDR · SOC 戰情中心**（`web/public/logo.png`）  
- `web/dist` 由 FastAPI `SPAStaticFiles` 提供（`/login` 等深連結可刷新）  
- Session：**HttpOnly cookie** `soc_session`（非 localStorage JWT）  
- `TenantProvider`（`web/src/TenantContext.tsx`）統一帶 `tenant` query 至 overview / cases / case detail  
- `platform_admin` / `tenant_admin` 顯示「設定中心 → 帳號管理」「設定中心 → 外部整合器」  

### 5.6 Multi-tenant 資料隔離（Web 層）

Registry 權威來源：`config/stellar_tenants.json`（與 automation 相同，**非** UI 可編輯）。

| 角色 | API `tenant` query | 實際資料範圍 |
|------|-------------------|--------------|
| `platform_admin` / `soc_analyst` / `soc_viewer` | 空 = 全部 tenant | 所有 `incident_jira` / Stellar live |
| 同上 | `tenant=jjnet` | 僅 `tenant_source_id=jjnet` |
| `tenant_admin` / `tenant_viewer` | 忽略（強制自家） | 僅 `users.tenant_source_id`；帶其他 tenant → 403 |

| API | 隔離方式 |
|-----|----------|
| `GET /v1/demo/overview` | sync：`incident_jira.tenant_source_id`；live：API `tenant_id` + registry 精確過濾 |
| `GET /v1/demo/cases` | SQL `tenant_source_id` |
| `GET /v1/demo/cases/{id}` | 查 link 時帶 tenant；跨 tenant → **404**（不洩漏存在與否） |
| `GET /v1/demo/tenants` | Platform：全部 enabled；tenant 角色：僅自家一筆 |
| `/v1/admin/users` | `platform_admin`：全部；`tenant_admin`：僅自家 tenant 的 tenant 角色帳號 |
| `/v1/settings/integrations` | `platform_admin`：可見 tenants；`tenant_admin`：僅自家；`tenant_viewer` → 403 |
| `POST …/cycraft/test` | 同上；body 可帶未儲存表單值測試連線 |

**未隔離（刻意）：** `GET /v1/ai-data/*` — token 認證，供 MaiAgent／內部整合，非 session 使用者 API。

**程式：** `app/demo/tenant_access.py`、`app/demo/case_service.py`、`app/demo/live_overview.py`；`app/platform/tenant_scope.py`；測試 `tests/test_multi_tenant_demo.py`、`tests/test_tenant_live_filter.py`、`tests/test_tenant_settings.py`。

### 5.7 部署

```text
stellar-soc-api.service              # 127.0.0.1:8000（API + web/dist）
cloudflared-stellar-soc              # → https://xmdr.nine-security.com
ticket-api-stellar-jira              # Stellar 輪詢 / Jira（獨立）
cycraft-xcockpit-connector           # 選用；未 install 時不存在
```

詳見 [`CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md)。

### 5.8 資安（工程面，已實作）

| 項目 | 說明 |
|------|------|
| Session | HttpOnly cookie；`PLATFORM_EXPOSE_BEARER_TOKEN=false` |
| 登入 rate limit | 失敗次數限制（IP + email） |
| API 文件 | `/docs`、`/openapi.json` 關閉 |
| `AI_DATA_API_TOKEN` | 一律要求（無 localhost bypass） |
| Security headers | `app/middleware/security_headers.py` |
| TOTP 設定 | 不再於 JSON 回傳 raw `secret` |
| 最後 admin | 不可停用 / 降權 |

**未做：** Cloudflare Access / Zero Trust 政策（需 Cloudflare 後台手動）。

---

## 6. 實作進度

| 步驟 | 交付 | 狀態 |
|------|------|------|
| **D1** | `extract_affected_hosts`；`/v1/demo/overview` + `/cases`；測試 | ✅ |
| **D2** | `totp_policy` migration；`/v1/admin/users` CRUD；登入邏輯 | ✅ |
| **D3** | 前端：登入 + Layout + 路由 | ✅ |
| **D4** | 前端：儀表板（真實數字） | ✅ |
| **D5** | 前端：案件列表 + 詳情 | ✅ |
| **D6** | 前端：設定中心 → 帳號管理 | ✅ |
| **D7** | 老闆帳號、Cloudflare Tunnel、現場驗收 | ✅ |
| **D8** | 儀表板 P1/P2：時間窗 + AIxSOC 即時 + `new_in_window` | ✅ |
| **D9** | XSOC 案件編號、最近案件篩選、移除 Tenant 分布 | ✅ |
| **D10** | Multi-tenant：Tenant 選單、資料隔離、帳號管理 tenant 範圍、頂部個人名片 | ✅ |
| **D11** | CyCraft EDR 整合器併入 repo + 外部整合器 UI + systemd unit | ✅ |
| **D12** | Tenant 設定隔離、整合器 UI（+／儲存／Test）、DB 加密金鑰、AIxSOC 對外品牌 | ✅ |

**就緒標準（已達成）：** 老闆登入 https://xmdr.nine-security.com → 右上角切 Tenant（MSSP / JJNET）儀表板數字隨之變化 → 最近案件可篩「已建票」→ 點 XSOC 編號看詳情 → 帳號管理可開關 2FA／建立 tenant 客戶帳號。

### 6.1 後續待辦（非本階段）

| 優先 | 項目 | 說明 |
|------|------|------|
| P3 | Alerts 摘要（snapshot） | 儀表板 Alerts 指標 |
| P4 | Alerts 全量掃描 | 對齊 Stellar Alerts 視圖 |
| P5 | Users / Assets 趨勢 | **明確不做** |
| — | Cloudflare Access | 手動或另開工單 |
| — | 案件中心日期篩選 UI | API 可擴充 |
| — | 客戶 Portal / tenant registry UI | 見 PRD，非本階段 |

---

## 7. PRD 對照

| 項目 | Demo v0.4 | 完整 PRD |
|------|-----------|----------|
| 登入 + 2FA | ✅ per-user 政策 | 全域強制 → 之後對齊 |
| 儀表板 | ✅ AIxSOC 即時 + sync、時間窗、**tenant 範圍** | Client Overview 延後 |
| 案件 | ✅ 真實、唯讀、XSOC、**tenant 隔離** | 辦案/結案延後 |
| Multi-tenant Web | ✅ MSSP 切 tenant + tenant 角色隔離 | Client Portal 延後 |
| 設定 | ✅ 帳號管理（platform + tenant_admin） | 通知收件人等延後 |
| Jira | 不動 | Platform Ticket 延後 |
| Alerts 儀表板 | ⏸ P3/P4 | PRD 有規劃 |

---

## 8. 給老闆的說詞

「這是 **xMDR SOC 戰情中心**：MSSP 可在右上角切 **MSSP（全部）** 或單一客戶 tenant，儀表板與案件會跟著切；客戶帳號只能看自家資料。案件編號用 **XSOC**，後台 Jira automation 不變。」

---

## 9. 關鍵程式路徑（維護用）

| 區域 | 路徑 |
|------|------|
| Demo API | `app/routers/demo.py` |
| Tenant 隔離 | `app/demo/tenant_access.py` |
| 儀表板 sync | `app/demo/case_service.py` |
| 儀表板 live | `app/demo/live_overview.py`、`app/demo/overview_query.py` |
| XSOC 編號 | `app/demo/case_number.py`、`app/sync/case_id.py` |
| 平台 Auth | `app/platform/`、`app/routers/platform_auth.py` |
| 帳號管理 API | `app/routers/admin_users.py` |
| 外部整合器 API | `app/routers/tenant_settings.py`、`app/platform/tenant_secrets.py` |
| CyCraft 整合 | `app/integrations/cycraft/` |
| 前端 | `web/src/pages/`、`web/src/TenantContext.tsx`、`web/src/caseDisplay.ts` |
| SPA 靜態 | `app/spa_static.py` |
| 測試 | `tests/test_multi_tenant_demo.py`、`tests/test_tenant_live_filter.py`、`tests/test_tenant_settings.py`、`tests/test_tenant_secrets.py` |

## 10. 修訂紀錄

| 版本 | 日期 | 說明 |
|------|------|------|
| v0.1 | 2026-07-24 | 老闆 Demo：登入 + 儀表板 + 案件中心 |
| v0.2 | 2026-07-24 | 加設定中心帳號管理；確認真實 sync 資料；per-user 2FA |
| v0.3 | 2026-07-24 | **上線狀態**：xmdr.nine-security.com；P1/P2 儀表板；XSOC 編號；最近案件篩選；資安強化 |
| v0.4 | 2026-07-27 | Multi-tenant 資料隔離、MSSP Tenant 選單、個人名片 |
| v0.5 | 2026-07-27 | CyCraft EDR 整合器併入；設定中心「外部整合器」；`cycraft-xcockpit-connector.service` |
| v0.6 | 2026-07-27 | Tenant 設定硬邊界；`+` 新增整合器 UI；DB 加密金鑰；Test API；AIxSOC 對外品牌；multi-tenant poller |
