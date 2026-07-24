> **AI AGENTS — Tier 2.** Read **only** for Cloudflare Tunnel / `xmdr.nine-security.com` / `cloudflared`.  
> Skip for sync, cases, or dashboard logic.

# Cloudflare Tunnel — 對外暴露 Stellar SOC Web（GCP VM）

> 將 GCP 主機上的 `./serve_api`（預設 `:8000`，含 Web UI + `/v1/*` API）透過 Cloudflare Tunnel 安全發布到網際網路，**無需在 GCP 開放防火牆 80/443**。

## 架構

```text
使用者瀏覽器
    │ HTTPS（你的網域，例：soc.example.com）
    ▼
Cloudflare Edge
    │ Tunnel（加密出站）
    ▼
cloudflared（GCP VM 上常駐）
    │ http://127.0.0.1:8000
    ▼
./serve_api  →  FastAPI（/v1/auth、/v1/demo、靜態 web/dist）
```

**同一個 URL** 同時提供：

- Web UI（登入、儀表板、案件、帳號管理）
- API（`/v1/auth/*`、`/v1/demo/*`、`/v1/admin/*`）
- 可選 Webhook（`/v1/webhooks/jira-stellar`、`/v1/webhooks/line`）

常駐 **Stellar automation**（`ticket-api-stellar-jira.service`）與 Tunnel **分開**；Tunnel 只指到 HTTP API 服務。

---

## 前置條件

1. 網域已加入 **Cloudflare**（DNS 由 Cloudflare 代管）。
2. GCP VM 可出站 HTTPS（預設通常可以）。
3. 本機已可跑通：

```bash
./Tools/run web-build          # 若尚未建置 UI
./Tools/run platform-user create boss@example.com 'Passw0rd123!' \
  --role platform_admin --totp-policy off
./serve_api                    # 確認 http://127.0.0.1:8000/health 回 ok
```

4. `.env` 已設定 `PLATFORM_SECRET_KEY`（≥32 字元）、`PLATFORM_ENABLED=true`。

---

## 方式 A：API 自動設定（推薦）

**不要把 API Token 貼在聊天室。** 在伺服器 `/opt/stellar-jira/.env` 只需填：

```env
CLOUDFLARE_API_TOKEN=你的_token
CLOUDFLARE_TUNNEL_HOSTNAME=xmdr.nine-security.com
```

其餘已預設（tunnel 名稱、origin、Account ID 自動解析）。

建立 [API Token](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) 權限：

| 類型 | 權限 |
|------|------|
| Account | Cloudflare Tunnel **Edit** |
| Zone `nine-security.com` | DNS **Edit** |

### 1. 預裝（不需 Token）

```bash
sudo ./Tools/run cloudflare-tunnel-setup --preflight
curl -s http://127.0.0.1:8000/health
```

會安裝 `cloudflared`、啟用 `stellar-soc-api.service`。

### 2. 填入 Token 後完成 Tunnel

```bash
# 預覽
./Tools/run cloudflare-tunnel-setup --dry-run

# 實際執行（建立/更新 Tunnel、ingress、DNS CNAME、systemd）
sudo ./Tools/run cloudflare-tunnel-setup
curl -s https://xmdr.nine-security.com/health
```

Token 存於 `.cloudflare/tunnel.token`（已 gitignore）。

---

## 方式 B：手動設定

```bash
# Debian/Ubuntu 範例
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main" | \
  sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
cloudflared --version
```

---

## 步驟 2：建立 Tunnel 並登入

```bash
cloudflared tunnel login
# 瀏覽器選擇網域，授權

cloudflared tunnel create stellar-soc
# 記下輸出的 Tunnel UUID
```

憑證會寫入 `~/.cloudflared/cert.pem`，Tunnel 憑證在 `~/.cloudflared/<UUID>.json`。

---

## 步驟 3：設定 ingress

複製範例並修改 hostname：

```bash
sudo mkdir -p /etc/cloudflared
sudo cp /opt/stellar-jira/deploy/cloudflared/config.yml.example /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml
```

必改：

- `tunnel:` → 你的 Tunnel **名稱**（`stellar-soc`）
- `credentials-file:` → `~/.cloudflared/<UUID>.json` 的**絕對路徑**
- `hostname:` → 例如 `soc.yourdomain.com`

驗證設定：

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

---

## 步驟 4：DNS 指向 Tunnel

```bash
cloudflared tunnel route dns stellar-soc soc.yourdomain.com
```

或在 Cloudflare Dashboard → DNS → CNAME `soc` → `<UUID>.cfargotunnel.com`。

---

## 步驟 5：systemd 常駐（建議）

### 5a. HTTP API（serve_api）

```bash
sudo install -m 644 /opt/stellar-jira/deploy/systemd/stellar-soc-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stellar-soc-api.service
curl -s http://127.0.0.1:8000/health
```

`stellar-soc-api.service` 預設 `HOST=127.0.0.1`（僅本機 + Tunnel 可連，較安全）。

### 5b. cloudflared

```bash
sudo install -m 644 /opt/stellar-jira/deploy/systemd/cloudflared-stellar-soc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared-stellar-soc.service
sudo systemctl status cloudflared-stellar-soc.service
```

### 5c. 確認

```bash
curl -s https://soc.yourdomain.com/health
```

瀏覽器開啟 `https://soc.yourdomain.com/` 應看到登入頁。

---

## 安全建議（強烈建議給老闆 Demo）

| 項目 | 建議 |
|------|------|
| **Cloudflare Access** | Zero Trust → Access → 對 `soc.yourdomain.com` 加 Email/OTP 政策，避免公開網路直接打登入頁 |
| **bind 127.0.0.1** | `serve_api` 只聽 localhost；對外只靠 Tunnel |
| **2FA** | 老闆帳號可 `totp_policy=off`；其他帳號用 UI 設 `required` |
| **GCP 防火牆** | 不必開 8000/443 給 0.0.0.0；Tunnel 為出站連線 |
| **Secrets** | `PLATFORM_SECRET_KEY`、Stellar/Jira token 留在 `.env`，勿提交 Git |

### 可選：Cloudflare Access 概念

```text
使用者 → Access 驗證（Email）→ 通過後 → Tunnel → serve_api
```

即使知道網址，未通過 Access 也進不了（多一層，與應用內登入互補）。

---

## Webhook（Jira / LINE）

若 Jira 或 LINE 要打到這台：

| 用途 | 公開 URL |
|------|----------|
| Jira → Stellar writeback | `https://soc.yourdomain.com/v1/webhooks/jira-stellar` |
| LINE webhook | `https://soc.yourdomain.com/v1/webhooks/line` |

`.env` 維持 `STELLAR_WEBHOOK_TOKEN` / `LINE_CHANNEL_SECRET` 等驗證；Cloudflare 僅轉發 HTTPS。

---

## 常見問題

### 開啟首頁正常，重新整理 `/cases` 404

確認 `serve_api` 已 build `web/dist`，且 `app/main.py` 有掛 `StaticFiles(..., html=True)`。Tunnel 應指到 **同一個** `serve_api`，不要另開純靜態伺服器。

### 502 Bad Gateway

1. `systemctl status stellar-soc-api` 是否在跑  
2. `config.yml` 的 `service: http://127.0.0.1:8000` 是否正確  
3. `cloudflared tunnel ingress validate`

### 只想暫時測試（不裝 systemd）

```bash
./serve_api &
cloudflared tunnel --config /etc/cloudflared/config.yml run
```

---

## 檔案對照

| 路徑 | 說明 |
|------|------|
| `deploy/cloudflared/config.yml.example` | Ingress 範例 |
| `deploy/systemd/cloudflared-stellar-soc.service` | cloudflared systemd |
| `deploy/systemd/stellar-soc-api.service` | serve_api systemd |
| `serve_api` | 本機 HTTP 入口（預設 8000） |

---

## 與現有 automation 的關係

| 服務 | systemd | 對外 |
|------|---------|------|
| `stellar-automation`（Jira 建票 poll） | `ticket-api-stellar-jira.service` | 不需要 |
| `serve_api`（Web + API） | `stellar-soc-api.service` | 經 Cloudflare Tunnel |
| `cloudflared` | `cloudflared-stellar-soc.service` | 出站至 Cloudflare |

兩者並行；**Tunnel 不會影響 Jira 建票機制**。
