import { AppShell } from '@/components/app-shell';
import { requireTenant } from '@/lib/tenant';

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const ctx = await requireTenant();
  return <AppShell ctx={ctx}>{children}</AppShell>;
}
