import { prisma } from '../client';
import { requireTenantId } from '../errors';

export async function dashboardSummary(tenantId: string) {
  requireTenantId(tenantId);
  const now = new Date();
  const weekAhead = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
  const startOfDay = new Date(now);
  startOfDay.setHours(0, 0, 0, 0);
  const endOfDay = new Date(now);
  endOfDay.setHours(23, 59, 59, 999);

  const [openTickets, weekSchedules, funnel, todayTodos, companyCount] =
    await Promise.all([
      prisma.ticket.count({
        where: { tenantId, status: { notIn: ['closed'] } },
      }),
      prisma.schedule.count({
        where: {
          tenantId,
          status: { notIn: ['cancelled'] },
          startAt: { gte: now, lt: weekAhead },
        },
      }),
      prisma.opportunity.groupBy({
        by: ['stage'],
        where: { tenantId },
        _count: { _all: true },
      }),
      prisma.activity.count({
        where: {
          tenantId,
          status: 'todo',
          dueAt: { gte: startOfDay, lte: endOfDay },
        },
      }),
      prisma.company.count({ where: { tenantId, deletedAt: null } }),
    ]);

  return { openTickets, weekSchedules, funnel, todayTodos, companyCount };
}

export async function reportSummary(tenantId: string) {
  requireTenantId(tenantId);
  const now = new Date();
  const weekStart = new Date(now);
  weekStart.setDate(now.getDate() - now.getDay() + 1);
  weekStart.setHours(0, 0, 0, 0);
  const weekEnd = new Date(weekStart.getTime() + 7 * 24 * 60 * 60 * 1000);

  const [funnel, ticketOpen, ticketClosed, weekScheduled, weekCompleted] =
    await Promise.all([
      prisma.opportunity.groupBy({
        by: ['stage'],
        where: { tenantId },
        _count: { _all: true },
      }),
      prisma.ticket.count({ where: { tenantId, status: { notIn: ['closed'] } } }),
      prisma.ticket.count({ where: { tenantId, status: 'closed' } }),
      prisma.schedule.count({
        where: { tenantId, startAt: { gte: weekStart, lt: weekEnd } },
      }),
      prisma.schedule.count({
        where: {
          tenantId,
          status: 'completed',
          updatedAt: { gte: weekStart, lt: weekEnd },
        },
      }),
    ]);

  return { funnel, ticketOpen, ticketClosed, weekScheduled, weekCompleted };
}
