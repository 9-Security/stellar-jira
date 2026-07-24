export type User = {
  id: string;
  email: string;
  role: string;
  tenant_source_id?: string | null;
  totp_enabled: boolean;
  totp_policy: string;
  is_active: boolean;
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
  const body = await res.json().catch(() => ({}));
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

export async function fetchOverview(params?: {
  window?: string;
  newBasis?: string;
  scope?: string;
}) {
  const qs = new URLSearchParams();
  if (params?.window) qs.set("window", params.window);
  if (params?.newBasis) qs.set("new_basis", params.newBasis);
  if (params?.scope) qs.set("scope", params.scope);
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

export async function fetchCase(id: string) {
  return api<{
    data: {
      case: Record<string, unknown>;
      affected_hosts: Array<{ hostname: string | null; ip: string | null }>;
      summary_text: string;
    };
  }>(`/v1/demo/cases/${encodeURIComponent(id)}`);
}

export async function fetchUsers() {
  return api<{ data: User[] }>("/v1/admin/users?include_inactive=true");
}

export async function createUser(payload: {
  email: string;
  password: string;
  role: string;
  totp_policy: string;
}) {
  return api<{ data: User }>("/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function patchUser(
  id: string,
  payload: Partial<{ is_active: boolean; totp_policy: string; role: string }>,
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
