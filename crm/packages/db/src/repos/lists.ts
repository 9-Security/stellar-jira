import { prisma } from '../client';
import { requireTenantId } from '../errors';

export async function listTickets(
  tenantId: string,
  opts?: {
    engineeringDefault?: boolean;
    membershipId?: string;
  },
) {
  requireTenantId(tenantId);
  return prisma.ticket.findMany({
    where: {
      tenantId,
      ...(opts?.engineeringDefault && opts.membershipId
        ? {
            OR: [
              { assigneeMembershipId: null },
              { assigneeMembershipId: opts.membershipId },
            ],
          }
        : {}),
    },
    orderBy: { updatedAt: 'desc' },
    include: {
      company: { select: { name: true } },
      assignee: { select: { user: { select: { name: true, email: true } } } },
    },
  });
}

export async function listOpportunities(tenantId: string) {
  requireTenantId(tenantId);
  return prisma.opportunity.findMany({
    where: { tenantId },
    orderBy: { updatedAt: 'desc' },
    include: { company: { select: { name: true } } },
  });
}

export async function listSchedules(tenantId: string) {
  requireTenantId(tenantId);
  return prisma.schedule.findMany({
    where: { tenantId },
    orderBy: { startAt: 'asc' },
    include: {
      assignee: { select: { user: { select: { name: true, email: true } } } },
    },
  });
}

export async function listContacts(tenantId: string) {
  requireTenantId(tenantId);
  return prisma.contact.findMany({
    where: { tenantId },
    orderBy: { updatedAt: 'desc' },
    include: { company: { select: { name: true } } },
  });
}
