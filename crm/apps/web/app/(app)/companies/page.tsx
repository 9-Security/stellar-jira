import { canWriteCompanies } from '@crm/shared';
import { CompanyList } from '@/components/company-list';
import { requireTenant } from '@/lib/tenant';

export default async function CompaniesPage() {
  const ctx = await requireTenant();
  return <CompanyList canWrite={canWriteCompanies(ctx.role)} />;
}
