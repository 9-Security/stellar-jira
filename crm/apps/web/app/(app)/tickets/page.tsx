import { listsRepo } from '@crm/db';
import { PRIORITY_LABELS, TICKET_STATUS_LABELS } from '@crm/shared';
import { EmptyState } from '@/components/empty-state';
import { PageHeader } from '@/components/app-shell';
import { SimpleTable } from '@/components/simple-table';
import { requireTenant } from '@/lib/tenant';

export default async function TicketsPage() {
  const ctx = await requireTenant();
  const rows = await listsRepo.listTickets(ctx.tenantId, {
    engineeringDefault: ctx.role === 'engineering',
    membershipId: ctx.membershipId,
  });
  return (
    <div>
      <PageHeader
        title="工單"
        description={
          ctx.role === 'engineering'
            ? '工程預設：未指派 + 指派給我'
            : 'Sprint 1：留言、狀態流與關聯排程'
        }
      />
      {rows.length === 0 ? (
        <EmptyState
          title="尚無工單"
          description="完整服務台（留言／內部備註）列於 Sprint 1。"
        />
      ) : (
        <SimpleTable
          headers={['標題', '狀態', '優先級', '公司', '負責人']}
          rows={rows.map((t) => [
            t.title,
            TICKET_STATUS_LABELS[t.status],
            PRIORITY_LABELS[t.priority],
            t.company?.name ?? '—',
            t.assignee?.user.name || t.assignee?.user.email || '未指派',
          ])}
        />
      )}
    </div>
  );
}
