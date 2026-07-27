export type User = {
  id: string;
  email: string;
  role: string;
  tenant_source_id?: string | null;
  totp_enabled: boolean;
  totp_policy: string;
  is_active: boolean;
};

export type TenantOption = {
  source_id: string;
  tenant_name?: string | null;
  customer_code: string;
  report_title?: string | null;
  sync_enabled: boolean;
};

async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, {
    ...options,
    headers,
    credentials: "include",
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const body = isJson ? await res.json().catch(() => ({})) : null;
  if (!isJson) {
    throw new Error(
      res.ok
        ? "伺服器回傳非 JSON（API 可能未就緒），請重新整理或聯絡管理員"
        : res.statusText || "Request failed",
    );
  }
  if (!res.ok) {
    const detail = (body as { detail?: string }).detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body as T;
}

export async function login(email: string, password: string) {
  return api<{
    access_token?: string;
    requires_totp?: boolean;
    login_token?: string;
    totp_setup_required?: boolean;
    user?: User;
  }>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function verifyTotp(login_token: string, code: string) {
  return api<{ access_token?: string; user: User }>("/v1/auth/totp/verify", {
    method: "POST",
    body: JSON.stringify({ login_token, code }),
  });
}

export async function logoutSession() {
  await api<{ ok: boolean }>("/v1/auth/logout", { method: "POST" });
}

export async function fetchMe() {
  return api<User>("/v1/auth/me");
}

export async function fetchTenants() {
  return api<{ data: TenantOption[] }>("/v1/demo/tenants");
}

export async function fetchOverview(params?: {
  window?: string;
  newBasis?: string;
  scope?: string;
  tenant?: string;
}) {
  const qs = new URLSearchParams();
  if (params?.window) qs.set("window", params.window);
  if (params?.newBasis) qs.set("new_basis", params.newBasis);
  if (params?.scope) qs.set("scope", params.scope);
  if (params?.tenant) qs.set("tenant", params.tenant);
  const suffix = qs.toString() ? `?${qs}` : "";
  return api<{
    summary: {
      total_cases: number;
      open_cases: number;
      critical_high_open: number;
      new_in_window: number;
    };
    by_severity: Record<string, number>;
    by_status: Record<string, number>;
    by_tenant: Record<string, number>;
    recent_cases: Array<Record<string, unknown>>;
    meta?: Record<string, unknown>;
  }>(`/v1/demo/overview${suffix}`);
}

export async function fetchCases(params: URLSearchParams) {
  return api<{
    data: Array<Record<string, unknown>>;
    pagination: { total: number; limit: number; offset: number };
  }>(`/v1/demo/cases?${params}`);
}

export async function fetchCase(id: string, tenant?: string) {
  const qs = new URLSearchParams();
  if (tenant) qs.set("tenant", tenant);
  const suffix = qs.toString() ? `?${qs}` : "";
  return api<{
    data: {
      case: Record<string, unknown>;
      affected_hosts: Array<{ hostname: string | null; ip: string | null }>;
      summary_text: string;
    };
  }>(`/v1/demo/cases/${encodeURIComponent(id)}${suffix}`);
}

export type CycraftConnector = {
  connector_type: "cycraft";
  enabled: boolean;
  xcockpit_customer_key?: string | null;
  stellar_xdr_ingest_path?: string | null;
  stellar_xdr_auth_path?: string | null;
  xcockpit_base_url?: string | null;
  secrets: {
    xcockpit_api_key: boolean;
    stellar_xdr_api_key: boolean;
    stellar_cases_api_key: boolean;
  };
  runtime_active: boolean;
  config_complete: boolean;
  tenant_source_id?: string;
  tenant_name?: string | null;
  report_title?: string | null;
  customer_code?: string;
};

export type TenantIntegration = {
  tenant_source_id: string;
  tenant_name?: string | null;
  report_title?: string | null;
  customer_code: string;
  connectors: CycraftConnector[];
  integrations: {
    cycraft: CycraftConnector;
  };
};

export type CycraftSettingsPatch = {
  enabled?: boolean;
  xcockpit_customer_key?: string | null;
  stellar_xdr_ingest_path?: string | null;
  stellar_xdr_auth_path?: string | null;
  xcockpit_base_url?: string | null;
  stellar_tenant_id?: string | null;
  xcockpit_api_key?: string | null;
  stellar_xdr_api_key?: string | null;
  stellar_cases_api_key?: string | null;
};

export type CycraftTestPayload = {
  xcockpit_customer_key?: string | null;
  stellar_xdr_ingest_path?: string | null;
  stellar_xdr_auth_path?: string | null;
  xcockpit_base_url?: string | null;
  xcockpit_api_key?: string | null;
  stellar_xdr_api_key?: string | null;
  stellar_cases_api_key?: string | null;
};

export async function fetchIntegrations() {
  return api<{
    data: TenantIntegration[];
    connectors: CycraftConnector[];
    meta: {
      scope: string;
      cycraft_service_enabled: boolean;
      connector_types: { id: string; label: string }[];
    };
  }>("/v1/settings/integrations");
}

export async function patchIntegration(
  tenantSourceId: string,
  payload: CycraftSettingsPatch,
) {
  return api<{ data: TenantIntegration }>(
    `/v1/settings/integrations/${encodeURIComponent(tenantSourceId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function testCycraftIntegration(
  tenantSourceId: string,
  payload?: CycraftTestPayload,
) {
  return api<{
    data: {
      ok: boolean;
      xcockpit: { ok?: boolean; error?: string; alert_batch_size?: number };
      stellar_xdr: { ok?: boolean; skipped?: boolean; error?: string; status_code?: number };
    };
  }>(
    `/v1/settings/integrations/${encodeURIComponent(tenantSourceId)}/cycraft/test`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    },
  );
}

export async function fetchUsers() {
  return api<{ data: User[] }>("/v1/admin/users?include_inactive=true");
}

export async function createUser(payload: {
  email: string;
  password: string;
  role: string;
  totp_policy: string;
  tenant_source_id?: string | null;
}) {
  return api<{ data: User }>("/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function patchUser(
  id: string,
  payload: Partial<{
    is_active: boolean;
    totp_policy: string;
    role: string;
    tenant_source_id: string | null;
  }>,
) {
  return api<{ data: User }>(`/v1/admin/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function resetUserTotp(id: string) {
  return api<{ data: User }>(`/v1/admin/users/${id}/totp-reset`, {
    method: "POST",
  });
}
