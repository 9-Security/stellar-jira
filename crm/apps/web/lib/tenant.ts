import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { tenantsRepo } from '@crm/db';
import type { Role } from '@crm/shared';

export const TENANT_COOKIE = 'crm-tenant-id';

export type TenantContext = {
  userId: string;
  email: string;
  name: string | null;
  tenantId: string;
  tenantName: string;
  tenantSlug: string;
  membershipId: string;
  role: Role;
  memberships: Array<{
    id: string;
    tenantId: string;
    role: Role;
    tenantName: string;
    tenantSlug: string;
  }>;
};

export async function getSessionUser() {
  const session = await auth();
  if (!session?.user?.id) return null;
  return {
    id: session.user.id,
    email: session.user.email ?? '',
    name: session.user.name ?? null,
  };
}

export async function getTenantContext(): Promise<
  | {
      user: NonNullable<Awaited<ReturnType<typeof getSessionUser>>>;
      memberships: [];
      ctx: null;
    }
  | {
      user: NonNullable<Awaited<ReturnType<typeof getSessionUser>>>;
      memberships: TenantContext['memberships'];
      ctx: TenantContext;
    }
  | null
> {
  const user = await getSessionUser();
  if (!user) return null;

  const rows = await tenantsRepo.listMembershipsForUser(user.id);
  const memberships = rows.map((m) => ({
    id: m.id,
    tenantId: m.tenantId,
    role: m.role,
    tenantName: m.tenant.name,
    tenantSlug: m.tenant.slug,
  }));

  if (memberships.length === 0) {
    return { user, memberships: [], ctx: null };
  }

  const jar = await cookies();
  const cookieTenant = jar.get(TENANT_COOKIE)?.value;
  const selected =
    memberships.find((m) => m.tenantId === cookieTenant) ?? memberships[0]!;
  const row = rows.find((r) => r.id === selected.id)!;

  return {
    user,
    memberships,
    ctx: {
      userId: user.id,
      email: user.email,
      name: user.name,
      tenantId: selected.tenantId,
      tenantName: row.tenant.name,
      tenantSlug: row.tenant.slug,
      membershipId: selected.id,
      role: selected.role,
      memberships,
    },
  };
}

export async function requireTenant(): Promise<TenantContext> {
  const result = await getTenantContext();
  if (!result) {
    redirect('/login');
  }
  if (!result.ctx) {
    redirect('/onboarding');
  }
  return result.ctx;
}
