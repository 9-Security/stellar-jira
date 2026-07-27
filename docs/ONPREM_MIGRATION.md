> **AI AGENTS — Tier 2.** GCP test → on-prem VM migration. Pair with `MAINTENANCE.md` deploy section.

# On-prem migration (GCP test → 地端 VM)

將 **stellar-jira** 從 GCP 測試機搬到地端 VM，同時保留：

- Stellar↔Jira automation 狀態（`stellar_sync_state.sqlite`）
- Platform 使用者與整合器設定（`platform.db`）
- Tenant registry（`config/stellar_tenants.json`）
- 對外 URL（`xmdr.nine-security.com`）— 透過 **Cloudflare Tunnel 改指向新 VM**

## 架構（遷移後）

```text
Internet → Cloudflare → cloudflared（地端 VM）→ 127.0.0.1:8000 stellar-soc-api
                                              ticket-api-stellar-jira（automation，無對外埠）
```

地端 VM **不需**開放 80/443；與 GCP 相同，僅需出站 HTTPS（Cloudflare、Stellar、Jira、LINE 等）。

---

## 前置：地端 VM 準備

| 項目 | 建議 |
|------|------|
| OS | Ubuntu 22.04/24.04 或同等 Linux |
| 路徑 | `/opt/stellar-jira`（與 systemd unit 一致） |
| 套件 | `python3 python3-venv git curl`；前端建置需 Node 20+（或從 bundle 帶 `web/dist`） |
| 帳號 | 服務以 root 或專用使用者跑 systemd（現行 unit 用 root + `WorkingDirectory`） |
| 磁碟 | ≥ 2GB 可用（含 `case_archive` 成長） |
| 網路 | 出站：Stellar API、Jira Cloud、LINE、Cloudflare；**不要**對全世界開 SSH |

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git curl
# 可選 Tunnel
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
```

---

## 步驟 1：GCP 匯出（來源機）

```bash
cd /opt/stellar-jira
git pull   # 確保含 migrate 腳本
chmod +x scripts/migrate_export_bundle.sh scripts/migrate_onprem_install.sh

# 會短暫停止 automation / API / tunnel
sudo ./scripts/migrate_export_bundle.sh
# → /tmp/stellar-jira-migrate-YYYYMMDD-HHMMSS.tar.gz
```

Bundle 內容：

| 路徑 | 說明 |
|------|------|
| `restore/.env` | 機密與開關 |
| `restore/data/platform.db` | 使用者、tenant_integrations |
| `restore/data/stellar_sync_state.sqlite` | 同步狀態、Jira 連結 |
| `restore/data/case_archive/` | 快照歸檔（若存在） |
| `restore/config/*.json` | tenant registry 等 |
| `restore/.cloudflare/tunnel.token` | Tunnel connector token |
| `restore/web/dist/` | 已建置 UI（可選） |

**安全傳輸：** `scp` / `rsync` over SSH 至地端，勿上傳至公開 bucket。

```bash
scp /tmp/stellar-jira-migrate-*.tar.gz user@onprem:/tmp/
```

---

## 步驟 2：地端安裝（目標機）

```bash
sudo mkdir -p /opt
sudo git clone git@github.com:9-Security/stellar-jira.git /opt/stellar-jira
cd /opt/stellar-jira
git checkout main   # 或與 GCP 相同 commit（見 bundle meta/source_host.txt）

chmod +x scripts/migrate_onprem_install.sh
sudo ./scripts/migrate_onprem_install.sh /tmp/stellar-jira-migrate-*.tar.gz
```

腳本會：還原 `.env` / data / config、建立 `.venv`、安裝 systemd、啟動服務。

若未帶 `web/dist`：

```bash
cd /opt/stellar-jira/web && npm ci && npm run build
sudo systemctl restart stellar-soc-api.service
```

---

## 步驟 3：驗證（地端）

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/health/ready
systemctl status stellar-soc-api.service ticket-api-stellar-jira.service cloudflared-stellar-soc.service
tail -50 /var/log/stellar_jira.log
./Tools/run tenant-health
./Tools/run stellar-verify
```

瀏覽器：`https://xmdr.nine-security.com` 登入、案件列表、設定中心。

---

## 步驟 4：Cloudflare 切換

**方式 A（推薦）：搬移 tunnel token**

Bundle 已含 `.cloudflare/tunnel.token`。地端 `cloudflared-stellar-soc.service` 啟動後，**同一 hostname 會連到新 VM**（舊 GCP 上的 cloudflared 須先停止，避免雙 connector 搶線）。

```bash
# GCP 上（切換前）
sudo systemctl stop cloudflared-stellar-soc.service

# 地端確認 tunnel active 後再測外網
curl -sI https://xmdr.nine-security.com/health
```

**方式 B：新建 Tunnel**

見 [`CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md) — 在地端跑 `./Tools/run cloudflare-tunnel-setup`，DNS 仍指向 `xmdr.nine-security.com`。

---

## 步驟 5：GCP 收尾

確認地端穩定 **24–48h** 後：

```bash
# GCP
sudo systemctl disable --now cloudflared-stellar-soc.service stellar-soc-api.service ticket-api-stellar-jira.service
# 可選：刪除 VM 或保留唯讀備份
```

---

## systemd 服務一覽

| 服務 | 用途 |
|------|------|
| `ticket-api-stellar-jira.service` | Stellar↔Jira automation |
| `stellar-soc-api.service` | Web UI + `/v1/*`（`127.0.0.1:8000`） |
| `cloudflared-stellar-soc.service` | 對外 Tunnel |
| `ticket-api-stellar-jira-watchdog.timer` | automation 看門狗（建議） |
| `cycraft-xcockpit-connector.service` | CyCraft（若啟用） |

日誌：

- `/var/log/stellar_jira.log` — automation
- `/var/log/stellar_soc_api.log` — API/UI

---

## 地端安全建議

| 項目 | 動作 |
|------|------|
| SSH | **勿** `ufw allow 22` 對全世界；限辦公室/VPN IP |
| `.env` | 權限 `600`；勿進 git |
| 公開 demo 結束 | `PLATFORM_PUBLIC_EXPOSURE=false` |
| TOTP | 所有帳號 `totp_policy=required` 且完成綁定 |
| Webhook | 啟用時設 `STELLAR_WEBHOOK_TOKEN`、`LINE_CHANNEL_SECRET` |

---

## 疑難排解

| 問題 | 檢查 |
|------|------|
| 外網 502 | 地端 `stellar-soc-api` / `cloudflared` 狀態；GCP tunnel 是否已停 |
| 重複建票 | 勿同時跑 GCP 與地端 automation |
| `platform.db` 鎖定 | 確認僅一個 `stellar-soc-api` 寫入 |
| UI 白屏 | `web/dist` 是否存在；`curl /v1/settings/integrations` 是否 JSON |
| Stellar 403 | `.env` `STELLAR_API_KEY` 與地端出站 IP 白名單（若 Stellar 有 IP 限制） |

---

## 相關文件

- [`MAINTENANCE.md`](MAINTENANCE.md) — 日常維運
- [`CLOUDFLARE_TUNNEL.md`](CLOUDFLARE_TUNNEL.md) — Tunnel 細節
- [`CURRENT_RUNTIME.md`](CURRENT_RUNTIME.md) — 同步行為
