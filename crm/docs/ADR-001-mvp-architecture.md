# ADR-001：SaaS CRM MVP 技術與架構決策

- **狀態**：Accepted（產品已鎖定 MVP 範圍）
- **日期**：2026-09-10
- **決策者**：Product（Nine-bot 協作產出）
- **影響範圍**：前端、後端、資料庫、Auth、部署、多租戶模型

---

## 1. Context（背景）

我們要打造一套 **純雲端、多租戶** 的 SaaS CRM，目標客戶不落地、不維運實體主機，只維護自家業務資料。

MVP 產品範圍包含：

1. **CRM 核心**：公司／聯絡人、商機漏斗、跟進活動、極簡報表  
2. **服務台**：類似 Jira 的案件／工單（狀態流、指派、留言／內部備註）  
3. **排程**：人員日曆、出勤任務與 booking；與工單 **鬆耦合**，必要時手動關聯  
4. **平台**：註冊登入、邀請、角色權限、租戶隔離

非目標（V2+）：SLA 引擎、複雜自動化、欄位級權限、郵件／電話深度整合、原生 App、客戶自架／私有化部署。

工程需要一份可執行的技術決策摘要，避免選型分歧與過早優化。

---

## 2. Decisions（決策）

### ADR-001a — 應用架構：Modular Monolith

**決策**：MVP 採 **模組化單體**（非微服務）。

**建議結構**：

- 預設（1–2 名全端）：**Next.js App Router monorepo**（UI + Route Handlers/Server Actions）  
- 若已有後端團隊：**Next.js（web）+ NestJS（api）** 同 monorepo，共用 `packages/db` / `packages/shared`

**理由**：人少、領域邊界尚未完全穩定；CRM／工單／排程共享租戶與權限模型，過早拆服務會增加分布式複雜度。

**後果**：

- (+) 部署簡單、交易一致性容易、迭代快  
- (−) 之後若要独立擴展排程或搜尋，需再抽服務（可接受，列為演化路徑）

---

### ADR-001b — 語言與前端棧

**決策**：

| 項目 | 選擇 |
|------|------|
| Language | TypeScript（前後端一致） |
| Web | Next.js（App Router） |
| Styling | Tailwind CSS + shadcn/ui |
| Data fetching / table | TanStack Query + TanStack Table |
| Calendar UI | FullCalendar 或 Schedule-X（擇一，全專案統一） |

**理由**：B2B 後台以表格、篩選、表單、日曆為主；該組合招聘面廣、元件生態成熟。

**後果**：前端與型別可與 Prisma schema／shared enum 對齊；日曆庫選定後勿混用兩套。

---

### ADR-001c — 資料層：PostgreSQL + Prisma

**決策**：

- DB：**PostgreSQL**（托管，例如 Supabase / RDS / Neon 等）  
- ORM / migration：**Prisma**  
- 主庫不做 MongoDB

**理由**：實體關聯密集（Company–Contact–Opportunity–Ticket–Schedule）；需要交易、索引、之後可加 Row Level Security。Prisma 利於 schema 審查與 TypeScript 型別生成。

**必要約定**：

- 業務表皆含 `tenant_id`  
- 擁有者／指派指向 `memberships.id`，不直接裸掛 `users.id`（除 auth 身份）  
- 狀態變更寫入 `status_events`  
- Ticket ↔ Schedule 經 `ticket_schedule_links`（M2M），取消關聯不級聯刪除對方

**索引最低要求**：

- `(tenant_id, updated_at)`  
- opportunities: `(tenant_id, stage)`  
- tickets: `(tenant_id, status, assignee_membership_id)`  
- schedules: `(tenant_id, assignee_membership_id, start_at)`

---

### ADR-001d — 多租戶模型：Shared DB + `tenant_id`

**決策**：MVP 使用 **共用資料庫、共用 schema、列級 `tenant_id` 隔離**。

**不採用（MVP）**：database-per-tenant、schema-per-tenant、客戶自建主機。

**實作強制**：

1. Request context 解析 `user_id` + 當前 `tenant_id`  
2. Repository / query 層 **強制** 注入 `tenant_id` 過濾；禁止無租戶條件的業務查詢  
3. 建立／關聯前驗證相關列同屬一 `tenant_id`  
4. 平台超管跨租戶僅限營運後台；租戶管理員不可跨租戶

**演化**：單租戶資料量或合規要求上升時，再評估 schema-per-tenant 或專用 DB；非 MVP 範圍。

**理由**：符合「客戶只維護資料、不維運主機」；上線最快、維運成本最低。

---

### ADR-001e — 身份與授權

**決策**：

- **Authentication**：Clerk **或** Auth.js（擇一）；負責登入／session／基本用戶身份  
- **Authorization**：自建 `memberships`（`tenant_id` + `user_id` + `role` + `status`）  
- MVP 角色：`admin` | `sales` | `support` | `engineering`

**權限摘要**（細節見產品權限矩陣）：

- admin：全租戶設定、邀請、強制關單／重開、全資料  
- sales：CRM 為主；排程以自己的為主  
- support / engineering：工單 + 排程；工程預設「未指派 + 指派給我」

**理由**：登入委託成熟服務商；**租戶成員關係與角色是產品核心**，必須自控。

**後果**：邀請流（`invites` → accept → membership）為 P0；不可只用「單一 org 外鍵」省略 membership。

---

### ADR-001f — API 風格

**決策**：MVP 使用 **REST JSON**；不做 GraphQL。

關鍵資源：`/companies`, `/contacts`, `/opportunities`, `/activities`, `/tickets`, `/schedules`, `/reports/summary`  
狀態變更：`POST /:resource/:id/transition`（配合伺服端狀態機校驗）  
排程衝突：回傳 `warnings[]`，**不阻擋儲存**（產品決策）

**共享合約**：`packages/shared` 存放 status/stage/priority/role enum，前後端同一來源。

---

### ADR-001g — 狀態機（產品＝工程合約）

| 實體 | 狀態 |
|------|------|
| Opportunity | `潛在 → 洽談 → 報價 → 成交` / `失單`（終態；重開→洽談） |
| Ticket | `開立 → 處理中 → 待回覆 → 完成 → 關閉` |
| Schedule | `已排程 → 進行中 → 完成` / `取消` |
| Activity（task） | `待辦 → 完成` |

**決策**：Ticket 完成 **不** 自動完成關聯 Schedule，反之亦然（鬆耦合）。

非法 transition 回 `409` 或 `422`，並寫 `status_events`。

---

### ADR-001h — 檔案、非同步、觀測、部署

| 項目 | MVP 決策 |
|------|----------|
| 物件儲存 | S3 相容（R2/S3）；附件可第二迭代再開 |
| Job Queue | 先同步處理；需要再加 Inngest 或 BullMQ |
| 觀測 | Sentry + 結構化 request log（含 tenant_id, user_id） |
| 託管 | 前端 Vercel；API/DB 用 Railway / Render / Fly 或 Supabase Postgres |
| 容器編排 | **不上 K8s**（MVP） |

**產品約束**：僅提供雲端 SaaS；文件與架構敘述避免暗示 on-prem 安裝包為一等公民。

---

## 3. Alternatives considered（曾考慮）

| 方案 | 未選原因 |
|------|----------|
| 微服務（CRM / Ticket / Schedule 分服務） | MVP 團隊規模與一致性成本不合適 |
| MongoDB 主庫 | 關聯與交易需求高 |
| DB / schema per tenant | 維運與遷移成本高；非當前客戶需求 |
| GraphQL | 額外棧複雜度；REST 足夠 |
| 自建 Auth 全套 | 安全與維護成本高；登入可外包 |
| Kubernetes | 純雲管服務已滿足；過早 |

---

## 4. Consequences（總體後果）

**正面**

- 與產品定位一致：純雲、多租戶、客戶零主機維運  
- 單一技術語系（TS）降低溝通成本  
- 租戶隔離與權限模型清晰，可審核  

**負面／技術債（已知）**

- Shared DB 需嚴格程式紀律（漏 `tenant_id` 即資料外洩風險）→ code review checklist + 整合測試必測跨租戶拒絕  
- 日曆與複雜排程（技能匹配、路線）未涵蓋  
- Auth 供應商與自建 membership 兩層，文件需寫清責任邊界  

**強制工程檢查清單**

- [ ] 所有業務 query 有 tenant scope 測試  
- [ ] transition 僅允許表定邊  
- [ ] Ticket–Schedule link 雙向可查、取消關聯不刪實體  
- [ ] shared enum 單一來源  
- [ ] 無 on-prem 安裝假設進入 CI/CD  

---

## 5. References（產品已鎖定產物）

- MVP 功能清單（平台 / CRM / 服務台 / 排程 / 極簡報表）  
- ER：Tenant, User, Membership, Company, Contact, Opportunity, Activity, Ticket, TicketComment, Schedule, TicketScheduleLink, Tag(ging), StatusEvent  
- API 草案與角色權限矩陣（admin / sales / support / engineering）

---

## 6. Follow-ups（建議下一份工程文件）

1. Sprint 0：repo 骨架、Prisma schema v1、Auth + membership 邀請流  
2. 狀態機單測表（各角色 × 合法／非法 transition）  
3. 威脅模型短文：租戶隔離、IDOR、邀請 token  

**本 ADR 變更流程**：若要改多租戶模型、主庫或拆微服務，需新開 ADR 並標註 supersede `ADR-001` 對應小節。
