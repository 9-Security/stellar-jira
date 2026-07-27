import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchIntegrations,
  patchIntegration,
  testCycraftIntegration,
  type CycraftConnector,
  type CycraftTestPayload,
} from "../api";
import { useTenant } from "../TenantContext";

const CONNECTOR_LABELS: Record<string, string> = {
  cycraft: "CyCraft Connector",
};

type FormState = {
  xcockpitApiKey: string;
  xcockpitCustomerKey: string;
  xcockpitBaseUrl: string;
  stellarXdrApiKey: string;
  stellarXdrIngestPath: string;
  stellarXdrAuthPath: string;
  stellarCasesApiKey: string;
};

const EMPTY_FORM: FormState = {
  xcockpitApiKey: "",
  xcockpitCustomerKey: "",
  xcockpitBaseUrl: "https://xcockpit.cycraft.ai",
  stellarXdrApiKey: "",
  stellarXdrIngestPath: "",
  stellarXdrAuthPath: "",
  stellarCasesApiKey: "",
};

function formFromConnector(conn: CycraftConnector): FormState {
  return {
    xcockpitApiKey: "",
    xcockpitCustomerKey: conn.xcockpit_customer_key || "",
    xcockpitBaseUrl: conn.xcockpit_base_url || "https://xcockpit.cycraft.ai",
    stellarXdrApiKey: "",
    stellarXdrIngestPath: conn.stellar_xdr_ingest_path || "",
    stellarXdrAuthPath: conn.stellar_xdr_auth_path || "",
    stellarCasesApiKey: "",
  };
}

function formToPayload(form: FormState, includeSecrets: boolean): CycraftTestPayload {
  const payload: CycraftTestPayload = {
    xcockpit_customer_key: form.xcockpitCustomerKey.trim() || null,
    xcockpit_base_url: form.xcockpitBaseUrl.trim() || null,
    stellar_xdr_ingest_path: form.stellarXdrIngestPath.trim() || null,
    stellar_xdr_auth_path: form.stellarXdrAuthPath.trim() || null,
  };
  if (includeSecrets) {
    if (form.xcockpitApiKey.trim()) payload.xcockpit_api_key = form.xcockpitApiKey.trim();
    if (form.stellarXdrApiKey.trim()) payload.stellar_xdr_api_key = form.stellarXdrApiKey.trim();
    if (form.stellarCasesApiKey.trim()) payload.stellar_cases_api_key = form.stellarCasesApiKey.trim();
  }
  return payload;
}

function ConnectorForm({
  tenantSourceId,
  tenantLabel,
  initial,
  onCancel,
  onSaved,
}: {
  tenantSourceId: string;
  tenantLabel: string;
  initial?: CycraftConnector;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<FormState>(
    initial ? formFromConnector(initial) : EMPTY_FORM,
  );
  const [error, setError] = useState("");
  const [testResult, setTestResult] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(
    Boolean(initial?.secrets?.stellar_cases_api_key),
  );

  async function save() {
    setSaving(true);
    setError("");
    setTestResult(null);
    try {
      await patchIntegration(tenantSourceId, {
        enabled: true,
        ...formToPayload(form, true),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "儲存失敗");
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setError("");
    setTestResult(null);
    try {
      const res = await testCycraftIntegration(
        tenantSourceId,
        formToPayload(form, true),
      );
      const x = res.data.xcockpit;
      const s = res.data.stellar_xdr;
      if (res.data.ok) {
        const parts = ["連線測試成功"];
        if (x.ok && x.alert_batch_size !== undefined) {
          parts.push(`XCockpit 告警批次：${x.alert_batch_size} 筆`);
        }
        if (s.skipped) {
          parts.push("AIxSOC 匯入驗證：未設定 Auth Path（已略過）");
        } else if (s.ok) {
          parts.push(`AIxSOC 匯入驗證：HTTP ${s.status_code}`);
        }
        setTestResult(parts.join(" · "));
      } else {
        const err = x.error || s.error || "連線測試失敗";
        setError(err);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "測試失敗");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="panel integration-form">
      <h3 style={{ marginTop: 0 }}>
        {initial ? "編輯" : "新增"} CyCraft Connector
        <span className="muted" style={{ fontWeight: 400, marginLeft: "0.5rem" }}>
          · {tenantLabel}
        </span>
      </h3>
      <p className="muted integration-form-note">
        CyCraft 告警會匯入 <strong>AIxSOC</strong> 平台既有案件管道，與您已啟用的 SOC 連線共用同一套案件與工單流程，
        不會另外建立第二套 SOC。請填寫 CyCraft 來源憑證，以及此來源專用的 AIxSOC 匯入 webhook（由 MSSP 提供）。
      </p>
      <h4 className="integration-section-title">CyCraft 來源</h4>
      <div className="form-row">
        <label>
          XCockpit API Key
          <input
            type="password"
            placeholder={initial?.secrets?.xcockpit_api_key ? "已設定（留空則不變更）" : "Authorization Token"}
            value={form.xcockpitApiKey}
            onChange={(e) => setForm({ ...form, xcockpitApiKey: e.target.value })}
          />
        </label>
        <label>
          Customer UUID
          <input
            value={form.xcockpitCustomerKey}
            onChange={(e) => setForm({ ...form, xcockpitCustomerKey: e.target.value })}
            placeholder="XCockpit Management Customer UUID"
          />
        </label>
        <label>
          XCockpit Base URL
          <input
            value={form.xcockpitBaseUrl}
            onChange={(e) => setForm({ ...form, xcockpitBaseUrl: e.target.value })}
          />
        </label>
      </div>
      <h4 className="integration-section-title">AIxSOC 匯入端點</h4>
      <p className="muted integration-form-note" style={{ marginTop: 0 }}>
        與全域 SOC 連線金鑰不同：此為 CyCraft 專用 webhook，告警匯入 AIxSOC 後仍走既有案件輪詢與工單同步，不會產生第二套案件庫。
      </p>
      <div className="form-row">
        <label>
          AIxSOC 匯入 API Key
          <input
            type="password"
            placeholder={initial?.secrets?.stellar_xdr_api_key ? "已設定（留空則不變更）" : "Bearer token"}
            value={form.stellarXdrApiKey}
            onChange={(e) => setForm({ ...form, stellarXdrApiKey: e.target.value })}
          />
        </label>
        <label>
          AIxSOC 匯入 Path
          <input
            value={form.stellarXdrIngestPath}
            onChange={(e) => setForm({ ...form, stellarXdrIngestPath: e.target.value })}
            placeholder="/webhook/.../ingest"
          />
        </label>
        <label>
          AIxSOC Auth Path（選填）
          <input
            value={form.stellarXdrAuthPath}
            onChange={(e) => setForm({ ...form, stellarXdrAuthPath: e.target.value })}
            placeholder="/webhook/.../auth"
          />
        </label>
      </div>
      <button
        type="button"
        className="btn secondary integration-advanced-toggle"
        onClick={() => setShowAdvanced((v) => !v)}
      >
        {showAdvanced ? "隱藏進階選項" : "顯示進階選項"}
      </button>
      {showAdvanced && (
        <div className="form-row" style={{ marginTop: "0.75rem" }}>
          <label>
            AIxSOC Cases API Key（選填，Incident 雙向同步）
            <input
              type="password"
              placeholder={initial?.secrets?.stellar_cases_api_key ? "已設定（留空則不變更）" : "僅 Incident 回寫時需要"}
              value={form.stellarCasesApiKey}
              onChange={(e) => setForm({ ...form, stellarCasesApiKey: e.target.value })}
            />
          </label>
        </div>
      )}
      {testResult && <div className="success-banner">{testResult}</div>}
      {error && <div className="error">{error}</div>}
      <div className="integration-form-actions">
        <button type="button" className="btn" onClick={save} disabled={saving}>
          {saving ? "儲存中…" : "儲存"}
        </button>
        <button type="button" className="btn secondary" onClick={runTest} disabled={testing}>
          {testing ? "測試中…" : "Test"}
        </button>
        <button type="button" className="btn secondary" onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  );
}

function ConnectorCard({
  connector,
  onEdit,
  onRemove,
  onTested,
}: {
  connector: CycraftConnector;
  onEdit: () => void;
  onRemove: () => void;
  onTested: (msg: string, err?: string) => void;
}) {
  const [testing, setTesting] = useState(false);
  const label =
    connector.report_title ||
    connector.tenant_name ||
    connector.tenant_source_id ||
    "Tenant";

  async function runTest() {
    if (!connector.tenant_source_id) return;
    setTesting(true);
    try {
      const res = await testCycraftIntegration(connector.tenant_source_id);
      if (res.data.ok) {
        const n = res.data.xcockpit.alert_batch_size;
        onTested(
          `XCockpit 連線成功${n !== undefined ? `（${n} 筆告警）` : ""}`,
        );
      } else {
        onTested(
          "",
          res.data.xcockpit.error || res.data.stellar_xdr.error || "測試失敗",
        );
      }
    } catch (e) {
      onTested("", e instanceof Error ? e.message : "測試失敗");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="panel integration-card">
      <div className="integration-card-header">
        <div>
          <h3 style={{ margin: 0 }}>{CONNECTOR_LABELS.cycraft}</h3>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            {label}
            {connector.customer_code ? ` · ${connector.customer_code}` : ""}
          </p>
        </div>
        <div>
          {connector.runtime_active ? (
            <span className="pill">運行中</span>
          ) : connector.config_complete ? (
            <span className="muted">已就緒</span>
          ) : (
            <span className="muted">設定未完成</span>
          )}
        </div>
      </div>
      <ul className="muted integration-card-meta">
        <li>Customer: {connector.xcockpit_customer_key || "—"}</li>
        <li>匯入 Path: {connector.stellar_xdr_ingest_path || "—"}</li>
        <li>
          API Keys: XCockpit {connector.secrets?.xcockpit_api_key ? "✓" : "✗"} ·
          AIxSOC 匯入 {connector.secrets?.stellar_xdr_api_key ? "✓" : "✗"}
        </li>
      </ul>
      <div className="integration-form-actions">
        <button type="button" className="btn secondary" onClick={runTest} disabled={testing}>
          {testing ? "測試中…" : "Test"}
        </button>
        <button type="button" className="btn secondary" onClick={onEdit}>
          編輯
        </button>
        <button type="button" className="btn danger" onClick={onRemove}>
          移除
        </button>
      </div>
    </div>
  );
}

export function SettingsIntegrationsPage() {
  const { tenant, tenants, isPlatformScope } = useTenant();
  const [connectors, setConnectors] = useState<CycraftConnector[]>([]);
  const [meta, setMeta] = useState<{
    cycraft_service_enabled: boolean;
    connector_types: { id: string; label: string }[];
  } | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const [formMode, setFormMode] = useState<"add" | "edit" | null>(null);
  const [editConnector, setEditConnector] = useState<CycraftConnector | null>(null);
  /** Locked tenant for open form — never follows the header dropdown after open. */
  const [formTenantSourceId, setFormTenantSourceId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const effectiveTenantId = isPlatformScope ? tenant : tenants[0]?.source_id || tenant;

  const lockedTenantId =
    formTenantSourceId || editConnector?.tenant_source_id || effectiveTenantId;

  const tenantLabelFor = (sourceId: string) =>
    tenants.find((t) => t.source_id === sourceId)?.report_title ||
    tenants.find((t) => t.source_id === sourceId)?.tenant_name ||
    sourceId ||
    "";

  function load() {
    setLoading(true);
    fetchIntegrations()
      .then((res) => {
        setConnectors(res.connectors ?? []);
        setMeta(res.meta);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "載入失敗"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (
      formMode === "add" &&
      formTenantSourceId &&
      effectiveTenantId &&
      effectiveTenantId !== formTenantSourceId
    ) {
      setFormMode(null);
      setEditConnector(null);
      setFormTenantSourceId(null);
      setError("Tenant 已變更，請重新開啟表單。");
      setSuccess("");
    }
  }, [effectiveTenantId, formMode, formTenantSourceId]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const visibleConnectors = useMemo(() => {
    if (isPlatformScope && tenant) {
      return connectors.filter((c) => c.tenant_source_id === tenant);
    }
    if (!isPlatformScope) {
      return connectors.filter((c) => c.tenant_source_id === effectiveTenantId);
    }
    return connectors;
  }, [connectors, tenant, isPlatformScope, effectiveTenantId]);

  const hasCycraftForTenant = connectors.some(
    (c) => c.connector_type === "cycraft" && c.tenant_source_id === effectiveTenantId,
  );

  function openAdd(typeId: string) {
    if (typeId !== "cycraft") return;
    if (!effectiveTenantId) {
      setError("請先在上方選擇 Tenant，再新增整合器。");
      setMenuOpen(false);
      return;
    }
    if (hasCycraftForTenant && isPlatformScope && !tenant) {
      setError("每個 Tenant 僅能有一組 CyCraft Connector；請先選擇 Tenant。");
      setMenuOpen(false);
      return;
    }
    if (hasCycraftForTenant) {
      setError("此 Tenant 已有 CyCraft Connector，請直接編輯。");
      setMenuOpen(false);
      return;
    }
    setEditConnector(null);
    setFormTenantSourceId(effectiveTenantId);
    setFormMode("add");
    setMenuOpen(false);
    setError("");
    setSuccess("");
  }

  async function removeConnector(conn: CycraftConnector) {
    if (!conn.tenant_source_id) return;
    setError("");
    try {
      await patchIntegration(conn.tenant_source_id, { enabled: false });
      setSuccess("已移除整合器");
      setFormMode(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "移除失敗");
    }
  }

  return (
    <>
      <div className="page-header-row">
        <div>
          <h1 className="page-title" style={{ marginBottom: 0 }}>設定中心 · 外部整合器</h1>
          <p className="muted" style={{ marginTop: "0.35rem" }}>
            將第三方 EDR 資料匯入 <strong>AIxSOC</strong> 平台。對外僅呈現 AIxSOC 品牌，設定僅套用於目前 Tenant。
          </p>
        </div>
        <div className="add-connector-wrap" ref={menuRef}>
          <button
            type="button"
            className="btn add-connector-btn"
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-haspopup="true"
          >
            +
          </button>
          {menuOpen && (
            <div className="connector-dropdown">
              {(meta?.connector_types ?? [{ id: "cycraft", label: "CyCraft Connector" }]).map(
                (opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className="connector-dropdown-item"
                    onClick={() => openAdd(opt.id)}
                  >
                    {opt.label}
                  </button>
                ),
              )}
            </div>
          )}
        </div>
      </div>

      {meta && (
        <p className="muted" style={{ marginBottom: "1rem" }}>
          服務總開關 <code>CYCRAFT_CONNECTOR_ENABLED</code>：
          <strong>{meta.cycraft_service_enabled ? "已啟用" : "未啟用"}</strong>
        </p>
      )}

      {success && <div className="success-banner">{success}</div>}
      {error && <div className="error">{error}</div>}

      {formMode && lockedTenantId && (
        <ConnectorForm
          tenantSourceId={lockedTenantId}
          tenantLabel={tenantLabelFor(lockedTenantId)}
          initial={formMode === "edit" ? editConnector ?? undefined : undefined}
          onCancel={() => {
            setFormMode(null);
            setEditConnector(null);
            setFormTenantSourceId(null);
          }}
          onSaved={() => {
            setFormMode(null);
            setEditConnector(null);
            setFormTenantSourceId(null);
            setSuccess("已儲存並同步至後端");
            load();
          }}
        />
      )}

      {loading ? (
        <p className="muted">載入中…</p>
      ) : visibleConnectors.length === 0 && !formMode ? (
        <div className="panel integration-empty">
          <p className="muted" style={{ margin: 0 }}>
            尚未設定外部整合器。點擊右上角 <strong>+</strong>，選擇 CyCraft Connector 並輸入 API 資訊。
          </p>
        </div>
      ) : (
        visibleConnectors.map((conn) => (
          <ConnectorCard
            key={`${conn.tenant_source_id}-${conn.connector_type}`}
            connector={conn}
            onEdit={() => {
              setEditConnector(conn);
              setFormTenantSourceId(conn.tenant_source_id || null);
              setFormMode("edit");
              setSuccess("");
              setError("");
            }}
            onRemove={() => removeConnector(conn)}
            onTested={(msg, err) => {
              if (err) setError(err);
              else {
                setSuccess(msg);
                setError("");
              }
            }}
          />
        ))
      )}
    </>
  );
}
