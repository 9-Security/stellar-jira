import { listsRepo } from '@crm/db';
import { EmptyState } from '@/components/empty-state';
import { PageHeader } from '@/components/app-shell';
import { SimpleTable } from '@/components/simple-table';
import { requireTenant } from '@/lib/tenant';

export default async function ContactsPage() {
  const ctx = await requireTenant();
  const contacts = await listsRepo.listContacts(ctx.tenantId);
  return (
    <div>
      <PageHeader title="聯絡人" description="Sprint 1：CRUD 與公司關聯" />
      {contacts.length === 0 ? (
        <EmptyState title="尚無聯絡人" description="聯絡人列表將於 Sprint 1 開放新建。" />
      ) : (
        <SimpleTable
          rows={contacts.map((c) => [
            `${c.lastName}${c.firstName}`,
            c.email ?? '—',
            c.company?.name ?? '—',
          ])}
          headers={['姓名', 'Email', '公司']}
        />
      )}
    </div>
  );
}
