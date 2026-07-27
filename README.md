> **AI AGENTS — DO NOT READ BY DEFAULT.** Human quick start; overlaps [`AGENTS.md`](AGENTS.md) + [`docs/CURRENT_RUNTIME.md`](docs/CURRENT_RUNTIME.md).  
> Use `AGENTS.md` and [`docs/README.md`](docs/README.md) for doc routing.

# stellar-jira

**Stellar Cyber ↔ Jira AIxSOC** 中介層 + **xMDR Web**（`web/`）。

> **地端新機 Git 部署：** [`docs/PRODUCTION_DEPLOY_ONPREM.md`](docs/PRODUCTION_DEPLOY_ONPREM.md)  
> `git clone https://github.com/9-Security/stellar-jira.git` → `sudo ./scripts/onprem_bootstrap.sh`

> **現行行為（給人與 AI）**：請先讀 [`docs/CURRENT_RUNTIME.md`](docs/CURRENT_RUNTIME.md)。  
> 過時規格在 [`docs/archive/`](docs/archive/) — **預設不要讀**。

本目錄可由 monorepo [`ticket-api`](../) 的 `deploy/export_stellar_tree.sh` 匯出產生；若仍用匯出流程，在 ticket-api 修改後重新匯出再提交。

## 快速開始

```bash
cp env.example .env          # 填 STELLAR_*、JIRA_*、可選 SYNC_API_TOKEN
# 編輯 config/stellar_tenants.json；多租戶設 STELLAR_MULTI_TENANT_ENABLED=true
bash Tools/setup_env.sh
./Tools/run stellar-verify
./Tools/run tenant-validate
./Tools/run stellar-sync-dry-run
./Tools/run stellar-poll
```

常駐（建議）：

```bash
./Tools/run stellar-automation
# 或 systemd: ticket-api-stellar-jira.service
# 每輪：global poll → tenant classify → create/poll-mirror → writeback
```

Webhook API（xMDR Web + 可選 webhook）：

```bash
./serve_api
# 或 systemd: stellar-soc-api.service（127.0.0.1:8000）
# xMDR UI + /v1/auth、/v1/demo、/v1/settings、/v1/admin
# POST /v1/webhooks/jira-stellar   可選即時 Jira → Stellar
# POST /v1/webhooks/line           LINE 查 ID
```

## 同步一覽（現行）

| | Status | Assignee | Comments / Activity |
|--|--------|----------|---------------------|
| Stellar → Jira | ✅ | ✅ | ✅ |
| Jira → Stellar | ✅ | ❌ | ✅ |

建票：僅 `Critical` / `High`。Low/Medium 升嚴重程度後由 poll 建票（不進 deferred 常駐佇列）。  
多租戶：單次全域 poll，以 `cust_id` + `tenant_name` 嚴格分類；unknown／disabled
case 進 quarantine。所有 tenant 可共用 `AIXSOC`，票以 `tenant-<source_id>` label 分離。  
詳見 [`docs/CURRENT_RUNTIME.md`](docs/CURRENT_RUNTIME.md)。

## 獨立 Git 倉庫

```bash
cd stellar-jira
git init
git add .
git commit -m "Initial commit: Stellar Cyber → Jira AIxSOC"
git remote add origin git@github.com:YOUR_ORG/stellar-jira.git
git push -u origin main
```

## 目錄

| 路徑 | 說明 |
|------|------|
| `app/stellar/` | Stellar API、建票、mirror、writeback |
| `app/stellar_sync/` | 輪詢、automation、mirror/writeback 週期 |
| `app/jira/` | Jira REST client |
| `app/sync/` | SQLite 狀態、案件編號、鎖、case snapshots |
| `app/notify/` | SOC Email + LINE（內文＝Jira Description）；可選 MaiAgent full-case |
| `app/integrations/cycraft/` | 可選 CyCraft → AIxSOC ingest connector |
| `app/platform/` | xMDR 登入、`platform.db`、tenant 設定 API |
| `web/` | xMDR React UI（`./Tools/run web-build` → `web/dist`） |
| `app/decision/` | Decision Intelligence（規則／稽核；Description 區塊預設關閉） |
| `config/` | 欄位／workflow／user map／decision 設定 |
| `docs/` | **現行**文件；`docs/archive/` 為歷史 |
| `AGENTS.md` | AI agent 閱讀政策 |
| `scripts/` | CLI（`Tools/run` 轉調） |

## 多租戶同步、管理與報表

1. 複製租戶設定：`cp config/stellar_tenants.example.json config/stellar_tenants.json`（每筆含 `source_id`、`customer_code`、`tenant_id`、`tenant_name`、`products` 與 enable flags）。
2. 安裝報表依賴已含於 `requirements.txt`（`python-docx`、`matplotlib`、`numpy`）。

```bash
# 探索／驗證／健康狀態
./Tools/run tenant-discover
./Tools/run tenant-validate
./Tools/run tenant-health

# 月報 Word（指定租戶 + 產品 + 月份）
./Tools/run report-monthly --tenant jjnet --product darktrace --month 2026-05

# 或日期區間
./Tools/run report-monthly --tenant jjnet --product darktrace --start 2026-05-01 --end 2026-05-31

# 事件 CSV/JSON
./Tools/run report-export --tenant jjnet --product darktrace --month 2026-05
```

Production 啟用 `STELLAR_MULTI_TENANT_ENABLED=true`。`STELLAR_TENANT_ID`
只保留給 legacy 單租戶模式；多租戶 poll 不使用它做 Cases API 篩選。
多個 tenant 時，報表必須用 `--tenant <source_id>`。

別名：`stellar-darktrace-monthly`、`stellar-darktrace-report`。

## Decision Intelligence（可選，預設啟用）

詳見 [`docs/DECISION_LAYER.md`](docs/DECISION_LAYER.md)。建票前會跑規則／知識決策，寫入 `decision_events`（與 sync SQLite 同庫），並可在結案 writeback 時回寫 TP／FP outcome。

```bash
./Tools/run decision-evaluate --case-id <stellar_case_id>
./Tools/run decision-outcome --jira-key AIXSOC-1 --true-positive false --root-cause "授權軟體"
./Tools/run decision-dataset --out data/decision_dataset.jsonl
./Tools/run decision-pilot-report --out data/decision_pilot_report.md
```

## 新環境部署檢查清單

將整個 `stellar-jira` 複製到另一台主機後，依序完成下列項目即可**獨立運作**（不需 monorepo `ticket-api`、不含 Cortex 線）。

### 1. 程式與依賴

```bash
cd /path/to/stellar-jira
cp env.example .env
bash Tools/setup_env.sh          # 建立 .venv、安裝 requirements.txt
```

- **不要**依賴來源機器的 `.venv`（建議在新環境重建）。
- `.env` **不會**隨目錄複製，需在新環境重新填寫。

### 2. 必填連線（`.env`）

| 變數 | 說明 |
|------|------|
| `STELLAR_BASE_URL` | Stellar DP 主機（不含 `/connect`） |
| `STELLAR_API_KEY` | System → Users → API Keys |
| `STELLAR_TENANT_ID` | 僅 legacy 單租戶模式；multi-tenant global poll 由 registry 分類 |
| `STELLAR_TENANTS_PATH` | Tenant registry（預設 `config/stellar_tenants.json`） |
| `STELLAR_MULTI_TENANT_ENABLED` | Production 設 `true`，忽略 Cases poll 的單一 tenant filter |
| `STELLAR_MULTI_TENANT_STRICT` | `true`：unknown／name mismatch case 進 quarantine |
| `JIRA_BASE_URL` | 例：`https://yourorg.atlassian.net` |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` | Jira Cloud API token |
| `STELLAR_JIRA_PROJECT_KEY` | AIxSOC 專案 key |

驗證：`./Tools/run stellar-verify`

### 3. Jira 欄位對照（依**該環境** Jira 調整）

| 檔案 | 用途 |
|------|------|
| `config/stellar_jira_field_map.example.json` | 自訂欄位 id（可複製改名並設 `STELLAR_JIRA_FIELD_MAP_PATH`） |
| `config/stellar_jira_workflow_status_map.json` | Jira workflow ↔ Stellar status |
| `config/stellar_resolution_tag_map.json` | Resolution tag ↔ Stellar tags |
| `.env` 內 `STELLAR_JIRA_*_FIELD` | 嚴重程度、狀態、告警名稱、案件編號等 field id |

### 4. 同步狀態（可選）

| 情境 | `data/stellar_sync_state.sqlite` |
|------|----------------------------------|
| 全新環境 | 不帶檔案，從頭同步 |
| 遷移／延續案件編號與已對照 case | **一併複製**此 SQLite |

### 5. 多租戶 registry（同步與報表共用）

```bash
cp config/stellar_tenants.example.json config/stellar_tenants.json
# 編輯 source_id、customer_code、tenant_id、tenant_name、products、enable flags
./Tools/run tenant-discover
./Tools/run tenant-validate
./Tools/run tenant-health
```

### 6. SOC 建票通知（可選：Email + LINE）

Jira 建票成功後（`stellar-poll` / `stellar-automation`）自動通知 SOC；`stellar-sync-dry-run` **不會**觸發。

**Email**（`.env`）：

| 變數 | 說明 |
|------|------|
| `SOC_NOTIFY_ENABLED` | `true` 啟用 |
| `SOC_NOTIFY_FROM` / `SOC_NOTIFY_TO` | 寄件人／收件人 |
| `SOC_NOTIFY_CC` / `SOC_NOTIFY_BCC` | 副本／密件副本（逗號分隔，可選） |
| `RESEND_API_KEY` 或 `SMTP_*` | 擇一 |

**LINE Bot 推播**（與 Email 共用主旨；**內文與 Jira Description 相同**；可只開 LINE、只開 Email、或兩者並用）：

| 變數 | 說明 |
|------|------|
| `LINE_NOTIFY_ENABLED` | `true` 啟用 |
| `LINE_CHANNEL_ACCESS_TOKEN` | Messaging API Channel access token |
| `LINE_NOTIFY_TO` | 收件人 ID，逗號分隔；`U…`（個人）或 `C…`（群組），各 **33 字元** |
| `LINE_CHANNEL_SECRET` | 僅 **Webhook 驗簽** 需要；日常推播不必開 Webhook |

查 User ID／Group ID（擇一）：

1. **Webhook 事件**（免費方案適用）：暫用 [webhook.site](https://webhook.site) 或 `./serve_api` + `POST /v1/webhooks/line`；從 `events[].source.userId`／`groupId` 複製（**不要**用 `destination`）。
2. `./Tools/run line-verify` — 驗證 ID 是否有效；`--push` 送測試訊息。
3. `./Tools/run line-list-followers` — 需 Messaging API 付費方案（免費常 403）。

**Stellar 可選 AI 摘要**（Groq）：`SOC_NOTIFY_AI_ENABLED=true`、`SOC_NOTIFY_AI_API_KEY`。失敗時預設仍寄信／推 LINE（`SOC_NOTIFY_AI_FAIL_OPEN=true`）。

**MaiAgent full-case**（可選）：`MAIAGENT_NOTIFY_ENABLED=true`。僅在
Critical/High **建票成功後**額外分析；SOC Email/Groq/LINE 原機制不變。
`MAIAGENT_NOTIFY_LINE_TO` 留空則共用 `LINE_NOTIFY_TO`；可選
`MAIAGENT_NOTIFY_EMAIL_TO`。手動驗證：`./Tools/run maiagent-trial`、
`./Tools/run maiagent-notify`。

`MAIAGENT_ALL_CASES_ENABLED` 會分析含 Low/Medium 的未建票 case，SOC 只處理
Critical/High 時請保持 **false**。若真要開，須另填
`MAIAGENT_ALL_CASES_LINE_TO`（不會沿用 `LINE_NOTIFY_TO`）。

```bash
./Tools/run notify-test     # 測試 Email + LINE（依 .env 開關）
./Tools/run notify-case --case-id <Stellar _id>   # 已開票 case 重寄通知
./Tools/run line-verify --push
```

詳見 `docs/MAINTENANCE.md` § SOC 建票通知、LINE Bot 推播。

### 7. Webhook API（可選）

```bash
# .env：STELLAR_WEBHOOK_TOKEN 或 SYNC_API_TOKEN（Jira 回寫，未設則 503）
# .env：LINE_CHANNEL_SECRET（LINE Webhook，未設則 503；推播本身不需 Webhook）
./serve_api
```

| 端點 | 用途 |
|------|------|
| `POST /v1/webhooks/jira-stellar` | Jira Automation → Stellar case 回寫（需 token） |
| `POST /v1/webhooks/line` | 接收 LINE 事件；記錄 ID 至 `data/line_recipients.json`（需 secret） |
| `GET /health`、`GET /health/ready` | 健康檢查 |

### 8. 常駐輪詢（systemd）

`deploy/systemd/ticket-api-stellar-jira.service` 預設路徑為 `/opt/stellar-jira`；若安裝在其他目錄，請修改 `WorkingDirectory`、`EnvironmentFile`、`ExecStart` 後：

```bash
sudo install -m 644 deploy/systemd/ticket-api-stellar-jira.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ticket-api-stellar-jira.service
```

日誌：`/var/log/stellar_jira.log`

### 8. xMDR Web + Cloudflare Tunnel（老闆 Demo / 正式對外）

與 automation **同一台 VM、分開 systemd**；詳見 [`docs/CLOUDFLARE_TUNNEL.md`](docs/CLOUDFLARE_TUNNEL.md)、[`docs/DEMO_MVP_v0.1.md`](docs/DEMO_MVP_v0.1.md)。

```bash
# .env 必填（platform）
PLATFORM_ENABLED=true
PLATFORM_SECRET_KEY=          # ≥32 字元隨機字串（新環境必換）
PLATFORM_DB_PATH=data/platform.db
AI_DATA_API_TOKEN=            # 若使用 /v1/ai-data
PLATFORM_COOKIE_SECURE=true   # 正式 HTTPS 建議 true（Tunnel 會帶 X-Forwarded-Proto）

# 建置 UI
./Tools/run web-build

# 建立管理員（新環境）
./Tools/run platform-user create admin@your.org '強密碼' \
  --role platform_admin --totp-policy off

# systemd
sudo install -m 644 deploy/systemd/stellar-soc-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stellar-soc-api.service
curl -s http://127.0.0.1:8000/health

# Tunnel（Token 只放 .env，完成後可刪 CLOUDFLARE_API_TOKEN）
# CLOUDFLARE_TUNNEL_HOSTNAME=xmdr.nine-security.com
sudo ./Tools/run cloudflare-tunnel-setup --preflight
sudo ./Tools/run cloudflare-tunnel-setup
curl -s https://xmdr.nine-security.com/health
```

**遷移 `platform.db`：** 若要保留既有帳號，複製 `data/platform.db`；否則在新機重建使用者。

**正式環境建議：** Cloudflare Access（Zero Trust）、老闆以外帳號 `totp_policy=required`、勿開放 GCP 8000 防火牆。

### 9. 部署後驗證

```bash
./Tools/run stellar-verify
./Tools/run tenant-validate
./Tools/run tenant-health
./Tools/run stellar-sync-dry-run
./Tools/run compile-check
./Tools/run stellar-cases-repro   # Cases LIST 診斷（原廠支援用）
./Tools/run notify-test           # 可選：SOC Email + LINE
./Tools/run line-verify           # 可選：LINE 收件人 ID
curl -s http://127.0.0.1:8000/health/ready   # stellar-soc-api
curl -s https://xmdr.nine-security.com/health # 若已設 Tunnel
```

**加固機制**（原廠修復前）：
- Stellar GET 逾時／5xx 可重試（`STELLAR_HTTP_MAX_RETRIES`，預設 1）
- inbound 失敗時 **略過該輪 writeback**（避免對已掛 API 加壓）
- **watchdog timer** 偵測 log 停滯（見 `docs/MAINTENANCE.md`）

### 本專案**不包含**

- Cortex XDR **直接 API 同步線**。本 repo 可針對已進入 Stellar case 的
  Cortex 類型 alerts 產出 tenant-scoped Cortex 月報。

## 從 monorepo 更新

在 **ticket-api 根目錄**：

```bash
./deploy/export_stellar_tree.sh          # 預設輸出到 ./stellar-jira
# 或
./Tools/run export-stellar-repo /path/to/stellar-jira
```

## 文件

| 文件 | 用途 |
|------|------|
| [`docs/CURRENT_RUNTIME.md`](docs/CURRENT_RUNTIME.md) | **現行**同步／cycle（source of truth） |
| [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) | 維運指令、systemd、notify |
| [`docs/DECISION_LAYER.md`](docs/DECISION_LAYER.md) | Decision Intelligence |
| [`docs/README.md`](docs/README.md) | 文件索引 |
| [`AGENTS.md`](AGENTS.md) | AI agent：只讀現行文件、略過 archive |
| [`docs/archive/`](docs/archive/) | **過時／歷史** — 預設勿讀 |
- 上游 monorepo：`ticket-api` 的 `docs/DEVELOPMENT.md` § Stellar
