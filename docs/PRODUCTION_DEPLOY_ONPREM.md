> **AI AGENTS — Tier 2.** Read only for on-prem VM bootstrap / git deploy / `/var/lib/xmdr` layout.

# 地端正式環境 — Git 部署

**Repo：** https://github.com/9-Security/stellar-jira  
**建議網域：** `xmdr.jjnetservice.com.tw`

## 目錄規劃（程式與資料分離）

```text
/opt/stellar-jira/     ← git clone（程式）
/var/lib/xmdr/         ← SQLite、archive、platform 帳號（備份此目錄）
/etc/xmdr/.env         ← 機密（不進 Git）
```

## 新 VM 一鍵部署

```bash
# 1. 安裝 git、python3-venv、nodejs（依發行版調整）
sudo apt update && sudo apt install -y git python3-venv python3-pip

# 2. Clone
sudo mkdir -p /opt/stellar-jira /var/lib/xmdr /etc/xmdr
sudo git clone https://github.com/9-Security/stellar-jira.git /opt/stellar-jira

# 3. 機密（從舊機 scp，或 cp env.example 後編輯）
sudo cp /opt/stellar-jira/env.example /etc/xmdr/.env
sudo chmod 640 /etc/xmdr/.env
sudo chown root:root /etc/xmdr/.env   # 或 root:xmdr + 群組可讀

# 4. Bootstrap（venv、web-build、data 連結、systemd）
cd /opt/stellar-jira
sudo ./scripts/onprem_bootstrap.sh

# 5. 從舊環境遷移資料（停舊機 automation 後）
# rsync -avz old:/var/lib/xmdr/ /var/lib/xmdr/

# 6. 驗證
./Tools/run stellar-verify
curl -s http://127.0.0.1:8000/health
```

## `.env` 資料路徑（可選絕對路徑）

預設使用 `data/` 符號連結 → `/var/lib/xmdr`。亦可改：

```env
STELLAR_SYNC_STATE_DB=/var/lib/xmdr/stellar_sync_state.sqlite
PLATFORM_DB_PATH=/var/lib/xmdr/platform.db
CASE_ARCHIVE_DIR=/var/lib/xmdr/case_archive
```

## 更新程式（不動資料）

```bash
cd /opt/stellar-jira
sudo git pull
./Tools/run web-build
sudo systemctl restart stellar-soc-api ticket-api-stellar-jira
```

## 對外網域

- **Nginx / Caddy** 反代至 `http://127.0.0.1:8000`（見機房標準）
- 或 **Cloudflare Tunnel**：`CLOUDFLARE_TUNNEL_HOSTNAME=xmdr.jjnetservice.com.tw`

`stellar-soc-api` 僅聽 `127.0.0.1:8000`。

## systemd 與 `.env`

服務依序讀取：`/etc/xmdr/.env` → `/opt/stellar-jira/.env`（後者可省略）。
