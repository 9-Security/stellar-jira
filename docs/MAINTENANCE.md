> **AI AGENTS — Tier 1 (ops).** Read for systemd, CLI, logs, reports, service restart.  
> Runtime behavior: `CURRENT_RUNTIME.md` wins on conflict.

# Stellar Cyber → Jira（AIxSOC）— maintenance

> **Runtime sync behavior:** see [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md) first.
> Archived / historical notes live under [`archive/`](archive/) — do not use for ops.

本 repo：**Stellar ↔ Jira** automation、`xMDR` Web（`web/` + `stellar-soc-api`）、可選 CyCraft 整合器；不含 Cortex XDR 線。

## 設定

```bash
cp env.example .env
# 填 STELLAR_BASE_URL、STELLAR_API_KEY、JIRA_*
# 多租戶：編輯 config/stellar_tenants.json，並設 STELLAR_MULTI_TENANT_ENABLED=true
bash Tools/setup_env.sh
./Tools/run stellar-verify
./Tools/run tenant-validate
```

## 同步架構（現行）

常駐 `stellar-automation` 每輪：

1. **Inbound poll** — 全域抓 lookback 內有變動的 case  
2. **Tenant classify** — `cust_id` + `tenant_name`；unknown／disabled 進 quarantine  
3. **Create** — 僅 `Critical` / `High`（見 global/per-tenant severity policy）  
4. **Poll mirror** — 已連結票：Status / Assignee / Case Activity → Jira  
5. **Writeback** — Status（+ resolution tag）→ Stellar；Jira `updated` 未變則跳過  
6. Sleep `STELLAR_AUTOMATION_INTERVAL_SECONDS`

| 方向 | Status | Assignee | Activity / comments |
|------|--------|----------|---------------------|
| Stellar → Jira | ✅ | ✅ | ✅ Case Activity → comment |
| Jira → Stellar | ✅ | ❌ | ✅ comment → Stellar（**僅 webhook**） |

- `STELLAR_MIRROR_ON_POLL=true`，`STELLAR_MIRROR_FULL_SCAN=false`  
- Low/Medium **不進** `deferred_create` 常駐佇列；升嚴重程度後靠 poll 建票；severity skip **不**全量 archive  
- 細節與衝突規則：[`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md)
- Stellar 原生 AI Summary 透過 MCP 拉取；完整 JSON 存 snapshot，精簡內容寫 Jira
  comment。未完成時依 `STELLAR_AI_SUMMARY_RETRY_SECONDS` 重試，且不阻斷建票。

## 指令

| 指令 | 說明 |
|------|------|
| `./Tools/run stellar-sync-dry-run` | 輪詢一輪，不建票、**不通知** |
| `./Tools/run stellar-poll` | 輪詢一輪並建 Jira；成功後觸發 SOC 通知 |
| `./Tools/run stellar-automation` | 常駐輪詢（見 `STELLAR_AUTOMATION_INTERVAL_SECONDS`） |
| `./Tools/run stellar-writeback --issue-key AIXSOC-1` | Jira → Stellar 回寫（單票） |
| `./Tools/run notify-test` | 測試 SOC 通知（預設 LOLBIN 範例；可 `--case-id`） |
| `./Tools/run notify-case --case-id <id>` | 已開票 case 重寄通知 |
| `./Tools/run line-verify` | 驗證 `LINE_NOTIFY_TO`；加 `--push` 測推播 |
| `./Tools/run stellar-case-export --ticket 1214` | 匯出完整 case＋alerts JSON（給本地長 context AI）；可 `--case-id`、`--out`、`--decision-meta`、`--include-comments` |
| `./Tools/run tenant-list` / `tenant-health` | 列 registry、每 tenant 同步統計、Jira link 與 quarantine |
| `./Tools/run tenant-discover [--apply]` | 從 Stellar 探索 tenants；`--apply` 只新增為 disabled，須人工啟用 |
| `./Tools/run tenant-validate` | 驗證 registry 的 ID/name 唯一性及 Stellar API 可見性 |
| `./Tools/run tenant-enable <source_id>` / `tenant-disable <source_id>` | 原子切換 `enabled`、`sync_enabled`、`reporting_enabled` 三個開關 |
| `./Tools/run tenant-quarantine` | 列出 unknown ID、名稱不符或 disabled 的 case |
| `./Tools/run tenant-backfill [--apply] [--assume <source_id>]` | 舊 Jira link 補 tenant metadata；無 snapshot 時須明確 `--assume` |
| `./Tools/run maiagent-trial --ticket 1214` | **旁路**試跑 MaiAgent（不寄 Email／LINE、不改 production Groq）；需 `MAIAGENT_API_KEY` + `MAIAGENT_CHATBOT_ID`；預設 base `https://api.sungcheng.org/api`；可 `--auth-check`、`--from-export`、`--agentic`（用 bot Skill＋完整 export）、`--context soc\|full`、`--mode chatbot\|openai`、`--compare-groq`、`--dry-run` |
| `./Tools/run maiagent-notify --ticket 1214` | 手動執行建票後 MaiAgent full-case 推播；LINE 空白則共用 `LINE_NOTIFY_TO`，Email 用 `MAIAGENT_NOTIFY_EMAIL_TO` |

狀態庫：`data/stellar_sync_state.sqlite`（勿提交 Git）。匯出檔預設在 `data/exports/`（亦勿提交）。

## systemd

```bash
sudo install -m 644 deploy/systemd/ticket-api-stellar-jira.service /etc/systemd/system/
sudo systemctl enable --now ticket-api-stellar-jira.service
```

**Watchdog（建議）**：

```bash
sudo install -m 755 scripts/systemd_watchdog_stellar_automation.sh /opt/stellar-jira/scripts/
sudo install -m 644 deploy/systemd/ticket-api-stellar-jira-watchdog.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ticket-api-stellar-jira-watchdog.timer
```

日誌：`/var/log/stellar_jira.log`

**自動化通知**：新建 Jira 成功後寄 **Email** / **LINE**（依 `.env`）。  
**變更 `app/` 後須重啟** service。

### xMDR Web（老闆 Demo UI）

| 服務 | 說明 |
|------|------|
| `stellar-soc-api.service` | FastAPI + `web/dist`，`127.0.0.1:8000` |
| `cloudflared-stellar-soc.service` | Tunnel → https://xmdr.nine-security.com |

```bash
./Tools/run web-build                              # 前端變更後（需 Node.js；見 Tools/run）
sudo systemctl restart stellar-soc-api.service     # API + web/dist — 外部整合器等 /v1/settings/*
sudo systemctl status cloudflared-stellar-soc.service
curl -s http://127.0.0.1:8000/health
```

**CyCraft EDR 整合器（選用）：**

```bash
# 全域：CYCRAFT_CONNECTOR_ENABLED=true、STELLAR_BASE_URL、輪詢間隔等（見 env.example）
# Per-tenant：xMDR → 設定中心 → 外部整合器（CyCraft 來源 + AIxSOC 匯入 webhook；金鑰存 platform.db 加密）
# 或 .env 後綴 VAR__TENANT_SUFFIX（例 `XCOCKPIT_API_KEY__JJNET` — suffix 依 registry `source_id`）— 不跨 tenant 共用
# 營運：CyCraft 目前套用 **jjnet**（JJNET），非 jjnet-edr
./Tools/run cycraft-test-xcockpit                  # CLI 探測 XCockpit（全域 .env）
sudo install -m 644 deploy/systemd/cycraft-xcockpit-connector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cycraft-xcockpit-connector.service   # 若未 install，service 為 not-found
```

- Poller：`app/integrations/cycraft/multi_poller.py`（每 enabled tenant 獨立設定與 state DB）
- 變更 automation / CyCraft **Python** 後：`sudo systemctl restart ticket-api-stellar-jira.service`（若僅 poller：`cycraft-xcockpit-connector.service`）

規格與進度見 [`DEMO_MVP_v0.1.md`](DEMO_MVP_v0.1.md)（v0.4：multi-tenant 資料隔離、MSSP Tenant 選單）；Tunnel 設定見 [`CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md)。**GCP → 地端 VM 遷移**見 [`ONPREM_MIGRATION.md`](ONPREM_MIGRATION.md)。

**Web 多租戶：** Platform 角色右上角 Tenant（MSSP＝全部）；tenant 角色僅見 `users.tenant_source_id`。Registry 與 automation 共用 `config/stellar_tenants.json`。

**HTTP 健康檢查**（`./serve_api` 或 `stellar-soc-api`）：`GET /health`、`GET /health/ready`。

**Stellar API 暫時異常**：該輪略過 writeback；浮水印不推進。診斷：`./Tools/run stellar-cases-repro`。

## 多租戶月報／事件匯出

設定檔：`config/stellar_tenants.json`（範例 `config/stellar_tenants.example.json`）。

Production 使用 `STELLAR_MULTI_TENANT_ENABLED=true`：只做一次全域 poll，再以
`cust_id` 為主、`tenant_name` 交叉驗證。未知／disabled case 進 quarantine，不建 Jira。
所有 tenant 預設共用 `AIXSOC`，票上以 `tenant-<source_id>` label 與 Description 的
Tenant / Tenant ID 拆分；月報仍用 `--tenant <source_id>`。
Tenant 重新啟用後，automation 會重試 quarantine 中可正確歸屬的 case。
保持 `STELLAR_POLL_SOURCE_ID=stellar`，不要改成 per-tenant source。

目前 registry：

| source_id | Stellar tenant | customer_code | products | 狀態 |
|-----------|----------------|---------------|----------|------|
| `jjnet` | `JJNET` | `JJNET` | darktrace, cortex | enabled | **CyCraft EDR 整合（營運 tenant）** |
| `jjnet-edr` | `JJNET-EDR` | `JJEDR` | cortex | enabled | EDR/Cortex；**非** CyCraft connector tenant |

| 指令 | 說明 |
|------|------|
| `./Tools/run report-monthly --tenant <source_id> --product darktrace --month YYYY-MM` | 月報 Word → `reports/` |
| `./Tools/run report-export --tenant <source_id> --product darktrace --month YYYY-MM` | 事件 CSV/JSON |

月報 Stellar 事件以 tenant API/filter 分離；Jira MTTR 以
`tenant-<source_id>` label 分離。新票自動帶 label；`tenant-backfill`
只補 SQLite metadata，不會修改舊 Jira 票的 labels。

## SOC 建票通知（Email + LINE）

建票成功後呼叫 `app/notify/ticket_created.py`；`--dry-run` **不觸發**。

### Email / LINE 內容

- **主旨**：XMDR 風格（偵測／遏止語意 + severity + event name）  
- **內文**：與 Jira Description **相同**（`stellar_case_detail_lines`）；可選 AI 區塊包在前後  
- 範例資料：`app/notify/stellar_sample_case.py`（`notify-test` 預設）

### Email 設定

1. `SOC_NOTIFY_ENABLED=true`、`SOC_NOTIFY_FROM`、`SOC_NOTIFY_TO`  
2. Resend 或 SMTP  
3. 可選 AI：`SOC_NOTIFY_AI_*`（Groq，給 SOC 廣播）
4. 可選 MaiAgent：`MAIAGENT_NOTIFY_*`（Critical/High **建票後** full-case 分析；
   LINE 空白則共用 `LINE_NOTIFY_TO`；Email 用 `MAIAGENT_NOTIFY_EMAIL_TO`）

全案例一次性分析（**不建議**；會含 Low/Medium）：

```env
MAIAGENT_ALL_CASES_ENABLED=false
MAIAGENT_ALL_CASES_LINE_TO=Uxxxxxxxx  # 若啟用則必填；不會沿用 LINE_NOTIFY_TO
MAIAGENT_ALL_CASES_RETRY_SECONDS=600
```

建票後 MaiAgent（建議；僅 Critical/High）：

```env
MAIAGENT_NOTIFY_ENABLED=true
MAIAGENT_NOTIFY_LINE_TO=          # 空白＝共用 LINE_NOTIFY_TO
MAIAGENT_NOTIFY_EMAIL_TO=you@example.com  # 可選額外信箱
MAIAGENT_NOTIFY_ASYNC=true
```

- SOC Email/Groq/LINE 原機制不變；MaiAgent 另推一則 `MaiAgent AI 分析:`。
- 僅在 Jira 建票成功後觸發（即 Critical/High）。
- `MAIAGENT_ALL_CASES_*` 請保持關閉，除非明確要分析未建票的 Low/Medium。

```bash
./Tools/run maiagent-notify --ticket 1214   # 手動測建票後 MaiAgent 推播
./Tools/run maiagent-trial --from-export data/exports/case_1214.json --agentic  # 不寄信試分析
```

### LINE

| 變數 | 說明 |
|------|------|
| `LINE_NOTIFY_ENABLED` | `true` 啟用 |
| `LINE_CHANNEL_ACCESS_TOKEN` | Push |
| `LINE_NOTIFY_TO` | `U…` / `C…` / `R…`，33 字元 |
| `LINE_CHANNEL_SECRET` | 僅 Webhook 驗簽 |

推播**不需** Webhook。查 ID：`webhook.site` 或 `POST /v1/webhooks/line`。

```bash
./Tools/run notify-test
./Tools/run notify-case --case-id <Stellar _id> [--jira-key AIXSOC-xxx]
./Tools/run line-verify [--push]
```

## Decision Intelligence

見 [`DECISION_LAYER.md`](DECISION_LAYER.md)。

- `DECISION_APPEND_JIRA_DESCRIPTION=false`：不要把 Decision 寫進 Description  
- `DECISION_JIRA_COMMENT_ON_CREATE=true`：建票後留 **值班檢查清單**（playbook 步驟；Description 保持乾淨）  
- `DECISION_OUTCOME_REMIND_ON_WRITEBACK=false`（預設）：不催 resolution tag；要做 Dataset 閉環再打開

目前產品重心是 **建票當下好用**；TP/FP／pilot 指標等標註習慣到位再強化。

```bash
./Tools/run decision-pilot-report --out data/decision_pilot_report.md
./Tools/run decision-outcome-backfill              # dry-run
./Tools/run decision-outcome-backfill --apply
./Tools/run decision-outcome --jira-key AIXSOC-1 --true-positive false --root-cause "授權軟體"
./Tools/run decision-dataset --out data/decision_dataset.jsonl
```

### Case snapshot 體積

同 case 只長期保留 milestone 全量快照（Decision 連結／最早／最新／jira／每級 severity 首筆），**不**對 alerts 做內容去重。

```bash
./Tools/run case-archive-gc           # dry-run
sudo ./Tools/run case-archive-gc --apply   # 刪非 milestone（含 root 擁有的 case_archive 檔）
# 若 SQLite 檔仍很大：sqlite3 data/stellar_sync_state.sqlite 'VACUUM;'
```

## Webhook（可選）

| 端點 | 認證 | 說明 |
|------|------|------|
| `POST /v1/webhooks/jira-stellar` | token | 可選即時回寫；**留言→Stellar 需走 webhook**；cycle 只回寫 Status 等欄位 |
| `POST /v1/webhooks/line` | LINE secret | 查收件人 ID |
| `GET /health` / `/health/ready` | 無 | 健康檢查 |

## 唯讀 Case API（`/v1/ai-data`）

從本機 SQLite snapshot／archive 撈已建票 case（不打 Stellar live API）。

| 端點 | 說明 |
|------|------|
| `GET /v1/ai-data/cases` | 列表（`tenant`、`limit`、`offset`） |
| `GET /v1/ai-data/cases/{jira_key}` | 單案（`include=case,alerts,observables,summary,activities,ai_summary`） |
| `GET /v1/ai-data/cases/{jira_key}/alerts` | alerts 分頁 |

認證：設 `AI_DATA_API_TOKEN` 後用 `Authorization: Bearer …` 或 `X-AI-Data-Token`；未設時僅允許 `127.0.0.1` / `::1`。

```bash
HOST=127.0.0.1 PORT=8000 ./serve_api
curl -s 'http://127.0.0.1:8000/v1/ai-data/cases?limit=5'
curl -s 'http://127.0.0.1:8000/v1/ai-data/cases/AIXSOC-61'
```

## 新環境部署檢查清單（摘要）

| 步驟 | 動作 |
|------|------|
| 1 | `cp env.example .env`，填 `STELLAR_*`、`JIRA_*` |
| 2 | `bash Tools/setup_env.sh` |
| 3 | 調整 `config/stellar_tenants.json`、其他 `stellar_*.json` 與 field id |
| 4 | 可選：複製 SQLite 狀態庫 |
| 5 | `tenant-discover` → `tenant-validate`；可選 SOC notify、MaiAgent、webhook token |
| 6 | `stellar-verify` → `tenant-health` → `stellar-sync-dry-run` |
| 7 | 對齊 [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md) 的 mirror/writeback 開關 |

## 安全

機密僅放 `.env`，勿提交 Git。
