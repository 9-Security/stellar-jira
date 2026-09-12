# Sprint 0 — 建置清單與完成定義（DoD）

- **日期**：2026-09-12
- **目標**：可登入的多租戶骨架 + schema v1 + 一個完整垂直切片（建議：公司 CRUD）證明租戶隔離  
- **預估**：約 1 週（2 人全端）／1.5–2 週（1 人）

---

## A. Repo 與工程基礎

- [ ] Monorepo 初始化（`apps/web`；若拆 API 則加 `apps/api`）  
- [ ] `packages/db`（Prisma）、`packages/shared`（role/status/stage/priority enum）  
- [ ] ESLint / Prettier / TypeScript strict  
- [ ] CI：install → lint → typecheck → test  
- [ ] 環境變數範例：`.env.example`（DATABASE_URL、AUTH_*、SENTRY_DSN）  
- [ ] README：如何啟動 web / migrate / seed  

**DoD**：clone 後依 README 可 local 跑起來；CI 綠燈。

---

## B. 資料庫 Schema v1

依 ADR-001 / ER 建立至少：

- [ ] `tenants`, `users`, `memberships`  
- [ ] `companies`, `contacts`  
- [ ] `opportunities`, `activities`  
- [ ] `tickets`, `ticket_comments`  
- [ ] `schedules`, `ticket_schedule_links`  
- [ ] `tags`, `taggings`（可第二週，若趕工可暫緩）  
- [ ] `status_events`  
- [ ] 必要索引（tenant_id 組合索引）  
- [ ] 遷移可重跑；seed：1 租戶、4 角色各 1 人、示範公司／工單／排程各 1–2 筆  

**DoD**：`prisma migrate` 在乾淨 DB 成功；seed 可登入四種角色驗證。

---

## C. Auth + 多租戶上下文

- [ ] 選定 Clerk **或** Auth.js（寫進 README，與 ADR 一致）  
- [ ] 登入／註冊  
- [ ] 建立租戶（首佔使用者 → admin membership）  
- [ ] 邀請：產生 token → 郵件可先 console／假送 → accept 建立 membership  
- [ ] Session／JWT 帶 `user_id`；request 解析 **當前 `tenant_id`**  
- [ ] Middleware：未登入擋業務路由；無 membership 導向 onboarding  

**DoD**：使用者 A 的租戶資料，使用者 B（另一租戶）API／UI 皆不可見（見 E）。

---

## D. 垂直切片：公司 CRUD（第一個完整功能）

- [ ] `GET/POST /companies`、`GET/PATCH/DELETE /companies/:id`（或 Server Actions 等價）  
- [ ] 列表頁 + 新建 + 詳情／編輯  
- [ ] 所有 query 強制 `tenant_id`  
- [ ] 角色：admin/sales 可寫；support/engineering 唯讀（或依權限矩陣）  
- [ ] 軟刪或刪除確認（與 IA 一致）  

**DoD**：E2E 或整合測試覆蓋「建立 → 列表看到 → 他租戶看不到」。

---

## E. 租戶隔離／IDOR 測試清單（P0）

自動化至少：

- [ ] 租戶 A 建立 company；租戶 B `GET` 該 id → 404（勿 403 洩漏存在）  
- [ ] 租戶 B `PATCH` / `DELETE` → 404  
- [ ] 邀請 token 單次使用／過期  
- [ ] 無 membership 無法帶任意 `tenant_id` 讀資料  
- [ ] （若已做關聯）跨租戶 id 寫入關聯 → 拒絕  

**DoD**：上述測試進 CI，失敗不可合併。

---

## F. 觀測與品質底線

- [ ] Sentry（或等價）接上前端＋後端  
- [ ] Request log 含 `request_id`, `tenant_id`, `user_id`（勿打密碼／token）  
- [ ] 健康檢查 `/health`（含 DB ping）  
- [ ] 錯誤頁／toast 不暴露 stack 給終端使用者  

**DoD**：故意拋錯可在 Sentry 看到租戶維度；health 供部署探針。

---

## G. 部署（預覽環境）

- [ ] 托管 Postgres  
- [ ] Preview／Staging 部署（Vercel + API/DB 依 ADR）  
- [ ] 遷移納入 release 步驟  
- [ ] Seed 僅限非正式環境  

**DoD**：產品與工程可用 staging URL 登入 seed 帳號點過公司 CRUD。

---

## H. Sprint 0 明確不做

- 完整商機看板、工單留言、排程日曆（列 Sprint 1+）  
- 真發信（可 stub）  
- 計費、檔案上傳、GraphQL、K8s  
- 原生 App  

---

## I. Sprint 1 預告（方便銜接）

1. 聯絡人 CRUD + 與公司關聯  
2. 商機 + transition + status_events  
3. 工單 + 留言  
4. 排程日曆 + 衝突 warnings  
5. Ticket ↔ Schedule 手動關聯  
6. 首頁摘要／報表  

---

## J. 簽核

| 項目 | Owner | 完成日 |
|------|-------|--------|
| Repo + CI | | |
| Schema + seed | | |
| Auth + 邀請 | | |
| 公司 CRUD | | |
| 隔離測試進 CI | | |
| Staging 可演示 | | |

**Sprint 0 完成定義（總）**：Staging 可演示「邀請成員 → 切角色 → 公司 CRUD」；跨租戶隔離測試在 CI 全過；ADR-001 無未決議的選型（Auth 供應商已二選一寫死）。
