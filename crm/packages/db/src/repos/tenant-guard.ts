import { prisma } from '../client';
import { TenantIsolationError, requireTenantId } from '../errors';

export async function assertMembershipInTenant(
  tenantId: string,
  membershipId: string,
): Promise<void> {
  requireTenantId(tenantId);
  const membership = await prisma.membership.findFirst({
    where: { id: membershipId, tenantId, status: 'active' },
    select: { id: true },
  });
  if (!membership) {
    throw new TenantIsolationError('Membership does not belong to this tenant');
  }
}

export async function assertCompanyInTenant(
  tenantId: string,
  companyId: string,
): Promise<void> {
  requireTenantId(tenantId);
  const company = await prisma.company.findFirst({
    where: { id: companyId, tenantId, deletedAt: null },
    select: { id: true },
  });
  if (!company) {
    throw new TenantIsolationError('Related company is not in this tenant');
  }
}
