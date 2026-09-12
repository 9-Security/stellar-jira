import { listsRepo } from '@crm/db';
import { OPPORTUNITY_STAGE_LABELS } from '@crm/shared';
import { EmptyState } from '@/components/empty-state';
import { PageHeader } from '@/components/app-shell';
import { SimpleTable } from '@/components/simple-table';
import { requireTenant } from '@/lib/tenant';

export default async function OpportunitiesPage() {
  const ctx = await requireTenant();
  const rows = await listsRepo.listOpportunities(ctx.tenantId);
  return (
    <div>
      <PageHeader title="商機" description="Sprint 1：看板、推進與 status_events" />
      {rows.length === 0 ? (
        <EmptyState
          title="尚無商機"
          description="階段操作與活動時間線將於下一迭代開放。"
        />
      ) : (
        <SimpleTable
          headers={['標題', '階段', '金額', '公司']}
          rows={rows.map((o) => [
            o.title,
            OPPORTUNITY_STAGE_LABELS[o.stage],
            o.amount ? String(o.amount) : '—',
            o.company?.name ?? '—',
          ])}
        />
      )}
    </div>
  );
}
