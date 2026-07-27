import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { fetchMe, type User } from "./api";
import { Layout } from "./components/Layout";
import { TenantProvider } from "./TenantContext";
import { CaseDetailPage } from "./pages/CaseDetail";
import { CasesPage } from "./pages/Cases";
import { DashboardPage } from "./pages/Dashboard";
import { LoginPage } from "./pages/Login";
import { SettingsIntegrationsPage } from "./pages/SettingsIntegrations";
import { SettingsUsersPage } from "./pages/SettingsUsers";

function AuthGate() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="muted">載入中…</p>;
  if (!user) return <Navigate to="/login" replace />;

  return (
    <TenantProvider user={user}>
      <Layout user={user}>
        <Outlet />
      </Layout>
    </TenantProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthGate />}>
          <Route index element={<DashboardPage />} />
          <Route path="cases" element={<CasesPage />} />
          <Route path="cases/:caseId" element={<CaseDetailPage />} />
          <Route path="settings/users" element={<SettingsUsersPage />} />
          <Route path="settings/integrations" element={<SettingsIntegrationsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
