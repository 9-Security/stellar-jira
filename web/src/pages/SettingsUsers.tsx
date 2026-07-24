import { type FormEvent, useEffect, useState } from "react";
import {
  createUser,
  fetchUsers,
  patchUser,
  resetUserTotp,
  type User,
} from "../api";

const ROLES = [
  "platform_admin",
  "soc_analyst",
  "soc_viewer",
  "tenant_admin",
  "tenant_viewer",
];

const TOTP_POLICIES = ["off", "optional", "required"];

export function SettingsUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("soc_analyst");
  const [totpPolicy, setTotpPolicy] = useState("optional");

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
      await createUser({
        email,
        password,
        role,
        totp_policy: totpPolicy,
      });
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

  async function onResetTotp(user: User) {
    await resetUserTotp(user.id);
    load();
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
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
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
                <td>{u.role}</td>
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
