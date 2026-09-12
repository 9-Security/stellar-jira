import type { Role } from '@crm/shared';
import { canWriteCompanies } from '@crm/shared';
import { prisma } from '../client';
import { ForbiddenError, NotFoundError, requireTenantId } from '../errors';
import { assertMembershipInTenant } from './tenant-guard';

export type CompanyInput = {
  name: string;
  website?: string | null;
  phone?: string | null;
  notes?: string | null;
  ownerMembershipId?: string | null;
};

function scoped(tenantId: string) {
  return { tenantId: requireTenantId(tenantId), deletedAt: null };
}

export async function listCompanies(tenantId: string) {
  return prisma.company.findMany({
    where: scoped(tenantId),
    orderBy: { updatedAt: 'desc' },
    include: {
      owner: {
        select: { id: true, role: true, user: { select: { name: true, email: true } } },
      },
    },
  });
}

export async function getCompany(tenantId: string, id: string) {
  const company = await prisma.company.findFirst({
    where: { ...scoped(tenantId), id },
    include: {
      owner: {
        select: { id: true, role: true, user: { select: { name: true, email: true } } },
      },
    },
  });
  return company;
}

/** Cross-tenant reads must look like missing rows (404), never 403. */
export async function getCompanyOrThrow(tenantId: string, id: string) {
  const company = await getCompany(tenantId, id);
  if (!company) {
    throw new NotFoundError('Company not found');
  }
  return company;
}

function assertWrite(role: Role) {
  if (!canWriteCompanies(role)) {
    throw new ForbiddenError('You cannot modify companies');
  }
}

export async function createCompany(tenantId: string, role: Role, input: CompanyInput) {
  requireTenantId(tenantId);
  assertWrite(role);
  const name = input.name.trim();
  if (!name) {
    throw new Error('Company name is required');
  }
  if (input.ownerMembershipId) {
    await assertMembershipInTenant(tenantId, input.ownerMembershipId);
  }
  return prisma.company.create({
    data: {
      tenantId,
      name,
      website: input.website?.trim() || null,
      phone: input.phone?.trim() || null,
      notes: input.notes?.trim() || null,
      ownerMembershipId: input.ownerMembershipId || null,
    },
  });
}

export async function updateCompany(
  tenantId: string,
  role: Role,
  id: string,
  input: Partial<CompanyInput>,
) {
  requireTenantId(tenantId);
  assertWrite(role);
  await getCompanyOrThrow(tenantId, id);
  if (input.ownerMembershipId) {
    await assertMembershipInTenant(tenantId, input.ownerMembershipId);
  }
  return prisma.company.update({
    where: { id },
    data: {
      ...(input.name !== undefined ? { name: input.name.trim() } : {}),
      ...(input.website !== undefined ? { website: input.website?.trim() || null } : {}),
      ...(input.phone !== undefined ? { phone: input.phone?.trim() || null } : {}),
      ...(input.notes !== undefined ? { notes: input.notes?.trim() || null } : {}),
      ...(input.ownerMembershipId !== undefined
        ? { ownerMembershipId: input.ownerMembershipId || null }
        : {}),
    },
  });
}

export async function softDeleteCompany(tenantId: string, role: Role, id: string) {
  requireTenantId(tenantId);
  assertWrite(role);
  await getCompanyOrThrow(tenantId, id);
  return prisma.company.update({
    where: { id },
    data: { deletedAt: new Date() },
  });
}
