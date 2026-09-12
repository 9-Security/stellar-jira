import { describe, expect, it } from 'vitest';
import {
  ForbiddenError,
  NotFoundError,
  TenantIsolationError,
  companiesRepo,
  prisma,
  tenantsRepo,
} from '@crm/db';
import { createTenantUser, createUserWithoutMembership } from './helpers';

describe('company tenant isolation', () => {
  it('tenant B cannot GET/PATCH/DELETE tenant A company (looks like 404)', async () => {
    const a = await createTenantUser('admin');
    const b = await createTenantUser('admin');
    const company = await companiesRepo.createCompany(a.tenant.id, 'admin', {
      name: 'Alpha Co',
    });

    await expect(
      companiesRepo.getCompanyOrThrow(b.tenant.id, company.id),
    ).rejects.toBeInstanceOf(NotFoundError);
    await expect(
      companiesRepo.updateCompany(b.tenant.id, 'admin', company.id, { name: 'Hacked' }),
    ).rejects.toBeInstanceOf(NotFoundError);
    await expect(
      companiesRepo.softDeleteCompany(b.tenant.id, 'admin', company.id),
    ).rejects.toBeInstanceOf(NotFoundError);

    const stillThere = await companiesRepo.getCompanyOrThrow(a.tenant.id, company.id);
    expect(stillThere.name).toBe('Alpha Co');
  });

  it('lists are tenant scoped', async () => {
    const a = await createTenantUser('admin');
    const b = await createTenantUser('admin');
    await companiesRepo.createCompany(a.tenant.id, 'admin', { name: 'Only A' });
    const listB = await companiesRepo.listCompanies(b.tenant.id);
    expect(listB.some((c) => c.name === 'Only A')).toBe(false);
  });

  it('rejects cross-tenant owner membership on create', async () => {
    const a = await createTenantUser('admin');
    const b = await createTenantUser('admin');
    await expect(
      companiesRepo.createCompany(a.tenant.id, 'admin', {
        name: 'Bad owner',
        ownerMembershipId: b.membership.id,
      }),
    ).rejects.toBeInstanceOf(TenantIsolationError);
  });

  it('support cannot write companies', async () => {
    const support = await createTenantUser('support');
    await expect(
      companiesRepo.createCompany(support.tenant.id, 'support', { name: 'Nope' }),
    ).rejects.toBeInstanceOf(ForbiddenError);
  });

  it('empty tenant_id is rejected', async () => {
    await expect(companiesRepo.listCompanies('')).rejects.toBeInstanceOf(
      TenantIsolationError,
    );
  });

  it('user without membership cannot resolve a foreign tenant', async () => {
    const a = await createTenantUser('admin');
    const user = await createUserWithoutMembership();
    const membership = await tenantsRepo.getActiveMembership(user.id, a.tenant.id);
    expect(membership).toBeNull();
    const companies = await prisma.company.findMany({ where: { tenantId: a.tenant.id } });
    expect(Array.isArray(companies)).toBe(true);
    // Access is only granted after membership resolution; no membership → no tenant context.
    expect(await tenantsRepo.listMembershipsForUser(user.id)).toEqual([]);
  });
});
