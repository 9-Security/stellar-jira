import { hash } from 'bcryptjs';
import { randomUUID } from 'node:crypto';
import { prisma } from '@crm/db';
import type { Role } from '@crm/shared';

export async function createTenantUser(role: Role, opts?: { tenantId?: string }) {
  const suffix = randomUUID().slice(0, 8);
  const tenant = opts?.tenantId
    ? await prisma.tenant.findUniqueOrThrow({ where: { id: opts.tenantId } })
    : await prisma.tenant.create({
        data: { name: `Tenant ${suffix}`, slug: `t-${suffix}` },
      });
  const user = await prisma.user.create({
    data: {
      email: `${role}-${suffix}@test.local`,
      name: role,
      passwordHash: await hash('Password123!', 10),
    },
  });
  const membership = await prisma.membership.create({
    data: {
      tenantId: tenant.id,
      userId: user.id,
      role,
      status: 'active',
    },
  });
  return { tenant, user, membership };
}

export async function createUserWithoutMembership() {
  const suffix = randomUUID().slice(0, 8);
  return prisma.user.create({
    data: {
      email: `nomem-${suffix}@test.local`,
      name: 'No Membership',
      passwordHash: await hash('Password123!', 10),
    },
  });
}
