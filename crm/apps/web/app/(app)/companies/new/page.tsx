import { redirect } from 'next/navigation';
import { canWriteCompanies } from '@crm/shared';
import { NewCompanyForm } from '@/components/new-company-form';
import { requireTenant } from '@/lib/tenant';

export default async function NewCompanyPage() {
  const ctx = await requireTenant();
  if (!canWriteCompanies(ctx.role)) {
    redirect('/?error=forbidden');
  }
  return <NewCompanyForm />;
}
