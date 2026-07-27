import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { caseHref, caseLabel, caseRowKey } from "../caseDisplay";
import { fetchCases } from "../api";
import { useTenant } from "../TenantContext";

export function CasesPage() {
  const { tenantQueryParam } = useTenant();
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [severity, setSeverity] = useState("");
  const [error, setError] = useState("");

  function load() {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (severity) params.set("severity", severity);
    if (tenantQueryParam) params.set("tenant", tenantQueryParam);
    fetchCases(params)
      .then((res) => {
        setRows(res.data);
        setTotal(res.pagination.total);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "載入失敗"));
  }

  useEffect(() => {
    load();
  }, [tenantQueryParam]);

  return (
    <>
      <h1 className="page-title">案件管理中心</h1>
      <div className="toolbar">
        <input
          placeholder="搜尋標題 / 編號"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">全部嚴重度</option>
          <option value="Critical">Critical</option>
          <option value="High">High</option>
          <option value="Medium">Medium</option>
          <option value="Low">Low</option>
        </select>
        <button className="btn" type="button" onClick={load}>
          搜尋
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="panel">
        <p className="muted">共 {total} 筆真實同步案件</p>
        <table>
          <thead>
            <tr>
              <th>編號</th>
              <th>標題</th>
              <th>Tenant</th>
              <th>嚴重度</th>
              <th>狀態</th>
              <th>更新</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={caseRowKey(c)}>
                <td>
                  {caseLabel(c) === "未建票" ? (
                    <span className="muted">未建票</span>
                  ) : (
                    <Link to={caseHref(c)}>{caseLabel(c)}</Link>
                  )}
                </td>
                <td>{String(c.title || "")}</td>
                <td>{String(c.tenant_name || c.tenant_source_id || "-")}</td>
                <td>
                  <span className={`pill ${String(c.severity || "").toLowerCase()}`}>
                    {String(c.severity || "-")}
                  </span>
                </td>
                <td>{String(c.status || "-")}</td>
                <td>{String(c.synced_at || "").slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
