# Nine CRM — Sprint 0

純雲端、多租戶 SaaS CRM 的工程骨架（ADR-001）。本目錄與上層 xMDR / Stellar-Jira 自動化**分開部署**。

## 鎖定選型（Sprint 0 DoD）

| 項目 | 選擇 |
|------|------|
| Auth | **Auth.js (NextAuth v5)** + Credentials（**不是 Clerk**） |
| 授權 | 自建 `memberships`（`tenant_id` + `user_id` + `role`） |
| 架構 | Next.js App Router modular monolith（`apps/web` Route Handlers） |
| DB | PostgreSQL + Prisma；共用 DB + 列級 `tenant_id` |
| API | REST JSON |
| 日曆 UI | Sprint 1 再鎖定 FullCalendar **或** Schedule-X |

產品約束：僅雲端 SaaS，不上 K8s、不做 GraphQL、不提供 on-prem 安裝包。

## 目錄

```
apps/web          Next.js UI + REST
packages/db       Prisma schema / client / tenant-scoped repos
packages/shared   role / status / stage / priority / 狀態機
tests             租戶隔離、邀請、狀態機（進 CI）
docs              ADR-001 / IA / Sprint 0 清單
```

## 本機啟動

需要 Node 20+ 與 PostgreSQL 16。

```bash
cd crm
cp .env.example .env          # 填 AUTH_SECRET（openssl rand -base64 32）
docker compose up -d          # 或使用已有 Postgres，改 DATABASE_URL

npm install
npm run db:migrate
npm run db:seed
npm run dev                   # http://localhost:3000
```

`npm run dev` / `build` 會從 repo 根目錄的 `crm/.env` 注入 `DATABASE_URL` 與 `AUTH_SECRET`（Next 預設只讀 `apps/web/.env`）。

沒有 Docker 時，把 `DATABASE_URL` 指到本機 Postgres，並先建立資料庫 `crm`。

### Seed 帳號（密碼皆 `Password123!`）

| Email | 角色 | 租戶 |
|-------|------|------|
| admin@acme.test | 管理員 | Acme |
| sales@acme.test | 業務 | Acme |
| support@acme.test | 客服（公司唯讀） | Acme |
| engineering@acme.test | 工程 | Acme |
| admin@beta.test | 管理員 | Beta（隔離對照） |
| multi@demo.test | Acme 管理員 + Beta 業務 | 切換租戶示範 |

**Seed 僅限 local / staging。** 正式環境設 `SEED_ENABLED=false`。

## 指令

| 指令 | 說明 |
|------|------|
| `npm run dev` | 啟動 web |
| `npm run db:migrate` | 套用 Prisma migration |
| `npm run db:migrate:dev` | 開發時產生 migration |
| `npm run db:seed` | 種子資料 |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest（含跨租戶 404 / 邀請單次使用） |
| `npm run build` | Next.js production build |

健康檢查：`GET /api/health`（含 DB ping）。

## 租戶隔離

- 所有業務 query 的第一個參數是 `tenantId`（不可省略）
- 跨租戶讀寫公司回 **404**（不回 403，避免洩漏資源存在）
- 邀請 token 以 SHA-256 存放；單次使用、7 天過期
- Session 只帶 `user_id`；`tenant_id` 來自 httpOnly cookie，且必須對應 active membership
- 郵件邀請為 **console stub**（不真發信）

## 部署（preview / staging）

1. 托管 Postgres（Neon / Supabase / RDS / Railway）
2. Vercel 部署 `apps/web`（root directory = `crm/apps/web` 或 monorepo include）
3. 環境變數：`DATABASE_URL`、`AUTH_SECRET`、`AUTH_URL`、可選 `SENTRY_DSN`
4. Release 步驟：`npm run db:migrate`（在 `crm/`）
5. Seed **不要**在 production 跑

Sentry：有 DSN 才初始化；request log 含 `request_id` / `tenant_id` / `user_id`，不打密碼或 token。

## Sprint 0 範圍外

完整商機看板、工單留言、排程日曆、真發信、計費、檔案上傳、GraphQL、K8s、原生 App。
