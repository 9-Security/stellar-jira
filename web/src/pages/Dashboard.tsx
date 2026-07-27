import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { caseHref, caseLabel, caseRowKey, isTicketed } from "../caseDisplay";
import { fetchOverview } from "../api";
import { useTenant } from "../TenantContext";

type OverviewMeta = {
  source?: string;
  window?: string;
  scope?: string;
  new_basis?: string;
};

type CaseRow = Record<string, unknown>;

const WINDOW_OPTIONS = [
  { value: "12h", label: "近 12 小時" },
  { value: "24h", label: "近 24 小時" },
  { value: "7d", label: "近 7 天" },
  { value: "all", label: "全部" },
];

const NEW_BASIS_OPTIONS = [
  { value: "created", label: "建立時間" },
  { value: "modified", label: "修改時間" },
];

const SEVERITY_OPTIONS = ["Critical", "High", "Medium", "Low"];

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

function BarList({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div className="panel">
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <p className="muted">無資料</p>
      ) : (
        <table>
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function sourceLabel(meta?: OverviewMeta): string {
  if (meta?.source === "stellar_live") return "AIxSOC 即時";
  if (meta?.source === "sync_db") return "AI SOC 同步";
  return "AI SOC 同步結果";
}

function matchesSearch(c: CaseRow, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const hay = [
    c.title,
    c.case_number,
    c.middleware_case_id,
    c.jira_key,
    c.stellar_case_id,
    c.tenant_name,
  ]
    .map((v) => String(v || "").toLowerCase())
    .join(" ");
  return hay.includes(needle);
}

export function DashboardPage() {
  const { tenantQueryParam, tenants, tenant, isPlatformScope } = useTenant();
  const [window, setWindow] = useState("12h");
  const [newBasis, setNewBasis] = useState("created");
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchOverview>> | null>(null);
  const [error, setError] = useState("");
  const [ticketFilter, setTicketFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [searchQ, setSearchQ] = useState("");

  const load = useCallback(() => {
    setError("");
    fetchOverview({ window, newBasis, tenant: tenantQueryParam })
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "載入失敗"));
  }, [window, newBasis, tenantQueryParam]);

  useEffect(() => {
    load();
  }, [load]);

  const statusOptions = useMemo(() => {
    if (!data) return [];
    const fromCases = data.recent_cases.map((c) => String(c.status || "").trim()).filter(Boolean);
    const fromSummary = Object.keys(data.by_status || {});
    return [...new Set([...fromCases, ...fromSummary])].sort();
  }, [data]);

  const filteredRecent = useMemo(() => {
    if (!data) return [];
    return data.recent_cases.filter((c) => {
      if (ticketFilter === "ticketed" && !isTicketed(c)) return false;
      if (ticketFilter === "unticketed" && isTicketed(c)) return false;
      if (severityFilter && String(c.severity || "").toLowerCase() !== severityFilter.toLowerCase()) {
        return false;
      }
      if (statusFilter && String(c.status || "") !== statusFilter) return false;
      if (!matchesSearch(c, searchQ)) return false;
      return true;
    });
  }, [data, ticketFilter, severityFilter, statusFilter, searchQ]);

  const newLabel =
    newBasis === "modified" ? "區間內新案（修改）" : "區間內新案（建立）";

  const scopeLabel = useMemo(() => {
    if (!isPlatformScope) {
      const own = tenants.find((t) => t.source_id === tenant);
      return own?.report_title || own?.tenant_name || tenant || "Tenant";
    }
    if (!tenant) return "MSSP（全部 Tenant）";
    const picked = tenants.find((t) => t.source_id === tenant);
    return picked?.report_title || picked?.tenant_name || tenant;
  }, [isPlatformScope, tenants, tenant]);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="muted">載入中…</p>;

  const meta = data.meta as OverviewMeta | undefined;
  const totalRecent = data.recent_cases.length;

  return (
    <>
      <h1 className="page-title">數據儀表板</h1>
      <div className="toolbar">
        <select
          value={window}
          onChange={(e) => setWindow(e.target.value)}
          aria-label="時間範圍"
        >
          {WINDOW_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={newBasis}
          onChange={(e) => setNewBasis(e.target.value)}
          aria-label="新案計算"
        >
          {NEW_BASIS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              新案：{o.label}
            </option>
          ))}
        </select>
        <button className="btn secondary" type="button" onClick={load}>
          重新整理
        </button>
      </div>
      <p className="muted">資料範圍：{scopeLabel} · 資料來源：{sourceLabel(meta)}</p>
      <div className="cards">
        <StatCard label="總案件數" value={data.summary.total_cases} />
        <StatCard label="開放中" value={data.summary.open_cases} />
        <StatCard label="Critical/High 開放" value={data.summary.critical_high_open} />
        <StatCard label={newLabel} value={data.summary.new_in_window} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
        <BarList title="嚴重度分布" data={data.by_severity} />
        <BarList title="狀態分布" data={data.by_status} />
      </div>
      <div className="panel">
        <h3>最近案件</h3>
        <div className="toolbar panel-toolbar">
          <input
            placeholder="搜尋標題 / 編號"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            aria-label="搜尋案件"
          />
          <select
            value={ticketFilter}
            onChange={(e) => setTicketFilter(e.target.value)}
            aria-label="建票狀態"
          >
            <option value="">全部建票狀態</option>
            <option value="ticketed">已建票</option>
            <option value="unticketed">未建票</option>
          </select>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            aria-label="嚴重度"
          >
            <option value="">全部嚴重度</option>
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label="狀態"
          >
            <option value="">全部狀態</option>
            {statusOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {(ticketFilter || severityFilter || statusFilter || searchQ) && (
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setTicketFilter("");
                setSeverityFilter("");
                setStatusFilter("");
                setSearchQ("");
              }}
            >
              清除篩選
            </button>
          )}
        </div>
        <p className="muted">
          顯示 {filteredRecent.length} / {totalRecent} 筆（最多 {totalRecent} 筆）
        </p>
        <table>
          <thead>
            <tr>
              <th>編號</th>
              <th>標題</th>
              <th>嚴重度</th>
              <th>狀態</th>
            </tr>
          </thead>
          <tbody>
            {filteredRecent.length === 0 ? (
              <tr>
                <td colSpan={4} className="muted">
                  無符合條件的案件
                </td>
              </tr>
            ) : (
              filteredRecent.map((c) => (
                <tr key={caseRowKey(c)}>
                  <td>
                    {caseLabel(c) === "未建票" ? (
                      <span className="muted">未建票</span>
                    ) : (
                      <Link to={caseHref(c)}>{caseLabel(c)}</Link>
                    )}
                  </td>
                  <td>{String(c.title || "")}</td>
                  <td>
                    <span className={`pill ${String(c.severity || "").toLowerCase()}`}>
                      {String(c.severity || "-")}
                    </span>
                  </td>
                  <td>{String(c.status || "-")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
