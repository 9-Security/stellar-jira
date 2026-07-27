import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { logoutSession, type User } from "../api";
import { useTenant } from "../TenantContext";

function canManageUsers(role: string): boolean {
  return role === "platform_admin" || role === "tenant_admin";
}

function emailInitials(email: string): string {
  const local = email.split("@")[0] || email;
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}

function roleLabel(role: string): string {
  return role.replace(/_/g, " ");
}

export function Layout({
  user,
  children,
}: {
  user: User;
  children?: React.ReactNode;
}) {
  const navigate = useNavigate();
  const { tenants, tenant, setTenant, isPlatformScope } = useTenant();
  const showUserAdmin = canManageUsers(user.role);

  async function logout() {
    try {
      await logoutSession();
    } catch {
      /* session may already be invalid */
    }
    navigate("/login");
  }

  const tenantLabel =
    tenants.find((t) => t.source_id === tenant)?.report_title ||
    tenants.find((t) => t.source_id === tenant)?.tenant_name ||
    tenant;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-logo" src="/logo.png" alt="JJNET" />
          <div className="brand-text">
            <h1>xMDR</h1>
            <div className="subtitle">SOC 戰情中心</div>
          </div>
        </div>
        <div className="badge">Live</div>
        <nav>
          <NavLink className="nav-link" to="/" end>
            數據儀表板
          </NavLink>
          <NavLink className="nav-link" to="/cases">
            案件管理中心
          </NavLink>
          {showUserAdmin && (
            <>
              <div className="nav-link muted" style={{ paddingTop: "1rem" }}>
                設定中心
              </div>
              <NavLink className="nav-link nav-sub" to="/settings/users">
                帳號管理
              </NavLink>
              <NavLink className="nav-link nav-sub" to="/settings/integrations">
                外部整合器
              </NavLink>
            </>
          )}
        </nav>
      </aside>
      <div className="content-column">
        <header className="top-bar">
          <div className="top-bar-right">
            {isPlatformScope && tenants.length > 0 && (
              <div className="scope-select">
                <label className="scope-select-label" htmlFor="tenant-select">Tenant</label>
                <select
                  id="tenant-select"
                  className="scope-select-input"
                  value={tenant}
                  onChange={(e) => setTenant(e.target.value)}
                >
                  <option value="">MSSP</option>
                  {tenants.map((t) => (
                    <option key={t.source_id} value={t.source_id}>
                      {t.report_title || t.tenant_name || t.source_id}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {!isPlatformScope && tenantLabel && (
              <div className="scope-chip">
                <span className="scope-chip-label">Tenant</span>
                <span className="scope-chip-value">{tenantLabel}</span>
              </div>
            )}
            <div className="profile-card">
              <div className="profile-avatar" aria-hidden="true">
                {emailInitials(user.email)}
              </div>
              <div className="profile-body">
                <div className="profile-email">{user.email}</div>
                <div className="profile-role">{roleLabel(user.role)}</div>
              </div>
              <button
                className="profile-logout"
                type="button"
                onClick={logout}
                title="登出"
              >
                登出
              </button>
            </div>
          </div>
        </header>
        <main className="main">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  );
}
