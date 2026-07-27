import { type FormEvent, useEffect, useState } from "react";
import {
  createUser,
  fetchMe,
  fetchUsers,
  patchUser,
  resetUserTotp,
  type User,
} from "../api";
import { useTenant } from "../TenantContext";

const PLATFORM_ROLES = ["platform_admin", "soc_analyst", "soc_viewer"];
const TENANT_ROLES = ["tenant_admin", "tenant_viewer"];
const ALL_ROLES = [...PLATFORM_ROLES, ...TENANT_ROLES];
const TOTP_POLICIES = ["off", "optional", "required"];

function isTenantRole(role: string): boolean {
  return TENANT_ROLES.includes(role);
}

export function SettingsUsersPage() {
  const { tenants } = useTenant();
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("soc_analyst");
  const [tenantSourceId, setTenantSourceId] = useState("");
  const [totpPolicy, setTotpPolicy] = useState("optional");

  const isPlatformAdmin = currentUser?.role === "platform_admin";
  const isTenantAdmin = currentUser?.role === "tenant_admin";
  const creatableRoles = isTenantAdmin ? TENANT_ROLES : ALL_ROLES;

  useEffect(() => {
    fetchMe().then(setCurrentUser).catch(() => setCurrentUser(null));
  }, []);

  useEffect(() => {
    if (isTenantAdmin && currentUser?.tenant_source_id) {
      setTenantSourceId(currentUser.tenant_source_id);
      if (!TENANT_ROLES.includes(role)) setRole("tenant_viewer");
    }
  }, [currentUser, isTenantAdmin, role]);

  function load() {
    fetchUsers()
      .then((res) => setUsers(res.data))
      .catch((e) => setError(e instanceof Error ? e.message : "載入失敗"));
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const payload: {
        email: string;
        password: string;
        role: string;
        totp_policy: string;
        tenant_source_id?: string | null;
      } = {
        email,
        password,
        role,
        totp_policy: totpPolicy,
      };
      if (isPlatformAdmin && isTenantRole(role)) {
        payload.tenant_source_id = tenantSourceId || null;
      }
      await createUser(payload);
      setEmail("");
      setPassword("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "建立失敗");
    }
  }

  async function toggleActive(user: User) {
    await patchUser(user.id, { is_active: !user.is_active });
    load();
  }

  async function changePolicy(user: User, policy: string) {
    await patchUser(user.id, { totp_policy: policy });
    load();
  }

  async function changeRole(user: User, newRole: string) {
    await patchUser(user.id, { role: newRole });
    load();
  }

  async function onResetTotp(user: User) {
    await resetUserTotp(user.id);
    load();
  }

  function tenantDisplay(sourceId?: string | null): string {
    if (!sourceId) return "—";
    const t = tenants.find((x) => x.source_id === sourceId);
    return t?.report_title || t?.tenant_name || sourceId;
  }

  return (
    <>
      <h1 className="page-title">設定中心 · 帳號管理</h1>
      {error && <div className="error">{error}</div>}
      <div className="panel">
        <h3>新增帳號</h3>
        <form onSubmit={onCreate}>
          <div className="form-row">
            <div>
              <label className="muted">Email</label>
              <input value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div>
              <label className="muted">初始密碼</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
          </div>
          <div className="form-row">
            <div>
              <label className="muted">角色</label>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {creatableRoles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            {isPlatformAdmin && isTenantRole(role) && (
              <div>
                <label className="muted">Tenant</label>
                <select
                  value={tenantSourceId}
                  onChange={(e) => setTenantSourceId(e.target.value)}
                  required
                >
                  <option value="">選擇 Tenant</option>
                  {tenants.map((t) => (
                    <option key={t.source_id} value={t.source_id}>
                      {t.report_title || t.tenant_name || t.source_id}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <label className="muted">2FA 政策</label>
              <select value={totpPolicy} onChange={(e) => setTotpPolicy(e.target.value)}>
                {TOTP_POLICIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn" type="submit">
            新增
          </button>
        </form>
      </div>
      <div className="panel">
        <h3>帳號列表</h3>
        <table>
          <thead>
            <tr>
              <th>Email</th>
              <th>角色</th>
              <th>Tenant</th>
              <th>2FA 政策</th>
              <th>已綁定</th>
              <th>狀態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>
                  {isPlatformAdmin ? (
                    <select
                      value={u.role}
                      onChange={(e) => changeRole(u, e.target.value)}
                    >
                      {ALL_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  ) : (
                    u.role
                  )}
                </td>
                <td>{tenantDisplay(u.tenant_source_id)}</td>
                <td>
                  <select
                    value={u.totp_policy}
                    onChange={(e) => changePolicy(u, e.target.value)}
                  >
                    {TOTP_POLICIES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{u.totp_enabled ? "是" : "否"}</td>
                <td>{u.is_active ? "啟用" : "停用"}</td>
                <td>
                  <button className="btn secondary" type="button" onClick={() => toggleActive(u)}>
                    {u.is_active ? "停用" : "啟用"}
                  </button>{" "}
                  <button className="btn secondary" type="button" onClick={() => onResetTotp(u)}>
                    重設 2FA
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
