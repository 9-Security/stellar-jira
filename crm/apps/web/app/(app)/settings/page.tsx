import { redirect } from 'next/navigation';
import { canAccessSettings } from '@crm/shared';
import { SettingsPanel } from '@/components/settings-panel';
import { requireTenant } from '@/lib/tenant';

export default async function SettingsPage() {
  const ctx = await requireTenant();
  if (!canAccessSettings(ctx.role)) {
    redirect('/?error=forbidden');
  }
  return <SettingsPanel />;
}
