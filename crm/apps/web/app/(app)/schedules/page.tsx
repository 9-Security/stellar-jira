import { listsRepo } from '@crm/db';
import { SCHEDULE_STATUS_LABELS, SCHEDULE_TYPE_LABELS } from '@crm/shared';
import { EmptyState } from '@/components/empty-state';
import { PageHeader } from '@/components/app-shell';
import { SimpleTable } from '@/components/simple-table';
import { requireTenant } from '@/lib/tenant';

export default async function SchedulesPage() {
  const ctx = await requireTenant();
  const rows = await listsRepo.listSchedules(ctx.tenantId);
  return (
    <div>
      <PageHeader title="排程" description="Sprint 1：週曆、衝突警告（不擋儲存）" />
      {rows.length === 0 ? (
        <EmptyState
          title="尚無排程"
          description="日曆視圖與工單鬆耦合關聯列於下一迭代。"
        />
      ) : (
        <SimpleTable
          headers={['標題', '類型', '狀態', '開始', '人員']}
          rows={rows.map((s) => [
            s.title,
            SCHEDULE_TYPE_LABELS[s.type],
            SCHEDULE_STATUS_LABELS[s.status],
            s.startAt.toISOString().slice(0, 16).replace('T', ' '),
            s.assignee?.user.name || s.assignee?.user.email || '—',
          ])}
        />
      )}
    </div>
  );
}
