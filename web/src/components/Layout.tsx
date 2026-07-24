import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { logoutSession, type User } from "../api";

export function Layout({
  user,
  children,
}: {
  user: User;
  children?: React.ReactNode;
}) {
  const navigate = useNavigate();
  const isAdmin = user.role === "platform_admin";

  async function logout() {
    try {
      await logoutSession();
    } catch {
      /* session may already be invalid */
    }
    navigate("/login");
  }

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
          {isAdmin && (
            <>
              <div className="nav-link muted" style={{ paddingTop: "1rem" }}>
                設定中心
              </div>
              <NavLink className="nav-link nav-sub" to="/settings/users">
                帳號管理
              </NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-footer">
          <div className="muted">{user.email}</div>
          <button className="btn secondary" style={{ marginTop: "0.75rem" }} onClick={logout}>
            登出
          </button>
        </div>
      </aside>
      <main className="main">
        {children ?? <Outlet />}
      </main>
    </div>
  );
}
