import Link from 'next/link';
import { reportsRepo } from '@crm/db';
import { OPPORTUNITY_STAGE_LABELS, type OpportunityStage } from '@crm/shared';
import { canWriteCompanies } from '@crm/shared';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { requireTenant } from '@/lib/tenant';

export default async function HomePage() {
  const ctx = await requireTenant();
  const summary = await reportsRepo.dashboardSummary(ctx.tenantId);
  const funnel = Object.fromEntries(
    summary.funnel.map((row) => [row.stage, row._count._all]),
  ) as Partial<Record<OpportunityStage, number>>;

  const cards = [
    { label: '未結工單', value: summary.openTickets, href: '/tickets' },
    { label: '本週排程', value: summary.weekSchedules, href: '/schedules' },
    { label: '今日待辦', value: summary.todayTodos, href: '/' },
    { label: '客戶數', value: summary.companyCount, href: '/companies' },
  ];

  return (
    <div>
      <PageHeader
        title={`你好，${ctx.name ?? ctx.email}`}
        description={`${ctx.tenantName} 摘要`}
        actions={
          <div className="flex gap-2">
            {canWriteCompanies(ctx.role) ? (
              <Link href="/companies/new">
                <Button>新建公司</Button>
              </Link>
            ) : null}
            <Link href="/tickets">
              <Button variant="outline">查看工單</Button>
            </Link>
          </div>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((c) => (
          <Link key={c.label} href={c.href}>
            <Card className="transition hover:border-accent/40">
              <CardBody>
                <p className="text-sm text-slate-500">{c.label}</p>
                <p className="mt-2 text-3xl font-semibold tracking-tight">{c.value}</p>
              </CardBody>
            </Card>
          </Link>
        ))}
      </div>
      <Card className="mt-6">
        <CardBody>
          <h2 className="text-sm font-semibold text-slate-800">商機漏斗摘要</h2>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {(Object.keys(OPPORTUNITY_STAGE_LABELS) as OpportunityStage[]).map(
              (stage) => (
                <div key={stage} className="rounded-xl bg-slate-50 px-3 py-3">
                  <div className="text-xs text-slate-500">
                    {OPPORTUNITY_STAGE_LABELS[stage]}
                  </div>
                  <div className="mt-1 text-xl font-semibold">{funnel[stage] ?? 0}</div>
                </div>
              ),
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
