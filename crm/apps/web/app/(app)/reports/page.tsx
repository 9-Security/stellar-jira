import { reportsRepo } from '@crm/db';
import { OPPORTUNITY_STAGE_LABELS, type OpportunityStage } from '@crm/shared';
import { PageHeader } from '@/components/app-shell';
import { Card, CardBody } from '@/components/ui/card';
import { requireTenant } from '@/lib/tenant';

export default async function ReportsPage() {
  const ctx = await requireTenant();
  const data = await reportsRepo.reportSummary(ctx.tenantId);
  const funnel = Object.fromEntries(
    data.funnel.map((row) => [row.stage, row._count._all]),
  ) as Partial<Record<OpportunityStage, number>>;

  return (
    <div>
      <PageHeader title="報表" description="極簡摘要 · MVP 無自訂報表、無匯出" />
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardBody>
            <h2 className="text-sm font-semibold">商機各階段數量</h2>
            <ul className="mt-3 space-y-1 text-sm">
              {(Object.keys(OPPORTUNITY_STAGE_LABELS) as OpportunityStage[]).map((s) => (
                <li key={s} className="flex justify-between">
                  <span className="text-slate-500">{OPPORTUNITY_STAGE_LABELS[s]}</span>
                  <span className="font-medium">{funnel[s] ?? 0}</span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <h2 className="text-sm font-semibold">工單未結／已關</h2>
            <p className="mt-3 text-3xl font-semibold">{data.ticketOpen}</p>
            <p className="text-sm text-slate-500">未結</p>
            <p className="mt-4 text-3xl font-semibold">{data.ticketClosed}</p>
            <p className="text-sm text-slate-500">已關閉</p>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <h2 className="text-sm font-semibold">本週排程／完成</h2>
            <p className="mt-3 text-3xl font-semibold">{data.weekScheduled}</p>
            <p className="text-sm text-slate-500">本週已排</p>
            <p className="mt-4 text-3xl font-semibold">{data.weekCompleted}</p>
            <p className="text-sm text-slate-500">本週完成</p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
