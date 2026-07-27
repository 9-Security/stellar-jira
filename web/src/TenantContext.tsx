import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { fetchTenants, type TenantOption, type User } from "./api";

const STORAGE_KEY = "xmdr_tenant_filter";

type TenantContextValue = {
  tenants: TenantOption[];
  tenant: string;
  setTenant: (sourceId: string) => void;
  isPlatformScope: boolean;
  tenantQueryParam: string | undefined;
};

const TenantContext = createContext<TenantContextValue | null>(null);

function isPlatformScope(role: string): boolean {
  return role === "platform_admin" || role === "soc_analyst" || role === "soc_viewer";
}

export function TenantProvider({
  user,
  children,
}: {
  user: User;
  children: ReactNode;
}) {
  const platformScope = isPlatformScope(user.role);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenant, setTenantState] = useState(() => {
    if (!platformScope) return user.tenant_source_id || "";
    return localStorage.getItem(STORAGE_KEY) || "";
  });

  const setTenant = useCallback(
    (sourceId: string) => {
      setTenantState(sourceId);
      if (platformScope) {
        if (sourceId) localStorage.setItem(STORAGE_KEY, sourceId);
        else localStorage.removeItem(STORAGE_KEY);
      }
    },
    [platformScope],
  );

  useEffect(() => {
    fetchTenants()
      .then((res) => {
        setTenants(res.data);
        if (!platformScope && user.tenant_source_id) {
          setTenantState(user.tenant_source_id);
        }
      })
      .catch(() => setTenants([]));
  }, [platformScope, user.tenant_source_id]);

  const tenantQueryParam = platformScope && tenant ? tenant : undefined;

  const value = useMemo(
    () => ({
      tenants,
      tenant,
      setTenant,
      isPlatformScope: platformScope,
      tenantQueryParam,
    }),
    [tenants, tenant, setTenant, platformScope, tenantQueryParam],
  );

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    throw new Error("useTenant must be used within TenantProvider");
  }
  return ctx;
}
