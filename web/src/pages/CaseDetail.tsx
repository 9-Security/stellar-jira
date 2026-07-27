import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchCase } from "../api";
import { useTenant } from "../TenantContext";

export function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const { tenantQueryParam } = useTenant();
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchCase>>["data"] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchCase(caseId, tenantQueryParam)
      .then((res) => setData(res.data))
      .catch((e) => setError(e instanceof Error ? e.message : "載入失敗"));
  }, [caseId, tenantQueryParam]);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="muted">載入中…</p>;

  const c = data.case;
  return (
    <>
      <p>
        <Link to="/cases">← 返回案件列表</Link>
      </p>
      <h1 className="page-title">{String(c.title || caseId)}</h1>
      <div className="cards">
        <div className="card">
          <div className="label">案件編號</div>
          <div className="value" style={{ fontSize: "1.1rem" }}>
            {String(c.case_number || c.jira_key || "-")}
          </div>
        </div>
        <div className="card">
          <div className="label">嚴重度</div>
          <div className="value">{String(c.severity || "-")}</div>
        </div>
        <div className="card">
          <div className="label">狀態</div>
          <div className="value">{String(c.status || "-")}</div>
        </div>
        <div className="card">
          <div className="label">Tenant</div>
          <div className="value" style={{ fontSize: "1rem" }}>
            {String(c.tenant_name || c.tenant_source_id || "-")}
          </div>
        </div>
      </div>
      <div className="panel">
        <h3>受影響主機 / IP</h3>
        {data.affected_hosts.length === 0 ? (
          <p className="muted">尚無主機／IP 資訊</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>主機名稱</th>
                <th>IP 位址</th>
              </tr>
            </thead>
            <tbody>
              {data.affected_hosts.map((h, i) => (
                <tr key={i}>
                  <td>{h.hostname || "—"}</td>
                  <td>{h.ip || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="panel">
        <h3>事件摘要</h3>
        <pre className="summary">{data.summary_text}</pre>
      </div>
    </>
  );
}
