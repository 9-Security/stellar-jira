import { NextResponse } from 'next/server';
import { z } from 'zod';
import { canAccessSettings } from '@crm/shared';
import { ForbiddenError, invitesRepo, prisma, tenantsRepo } from '@crm/db';
import { apiError, loadApiTenant } from '@/lib/api';
import { getSessionUser } from '@/lib/tenant';
import { setTenantCookie } from '@/lib/tenant-cookie';
import { logRequest } from '@/lib/log';

const createSchema = z.object({ name: z.string().min(1) });
const patchSchema = z.object({
  name: z.string().min(1).optional(),
  timezone: z.string().min(1).optional(),
});

export async function GET(req: Request) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const ctx = await loadApiTenant();
    if (!canAccessSettings(ctx.role)) {
      throw new ForbiddenError('Admin only');
    }
    const [members, invites, tenant] = await Promise.all([
      tenantsRepo.listTenantMembers(ctx.tenantId),
      invitesRepo.listInvites(ctx.tenantId),
      prisma.tenant.findUniqueOrThrow({ where: { id: ctx.tenantId } }),
    ]);
    logRequest({
      requestId,
      message: 'tenants.get',
      tenant_id: ctx.tenantId,
      user_id: ctx.userId,
    });
    return NextResponse.json({
      tenant: { name: tenant.name, timezone: tenant.timezone, slug: tenant.slug },
      members,
      invites,
    });
  } catch (err) {
    return apiError(err, { requestId });
  }
}

export async function POST(req: Request) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const user = await getSessionUser();
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const body = createSchema.parse(await req.json());
    const created = await tenantsRepo.createTenantForUser({
      userId: user.id,
      name: body.name,
    });
    await setTenantCookie(created.tenant.id);
    logRequest({
      requestId,
      message: 'tenants.create',
      tenant_id: created.tenant.id,
      user_id: user.id,
    });
    return NextResponse.json({ tenant: created.tenant }, { status: 201 });
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}

export async function PATCH(req: Request) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const ctx = await loadApiTenant();
    if (!canAccessSettings(ctx.role)) {
      throw new ForbiddenError('Admin only');
    }
    const body = patchSchema.parse(await req.json());
    const tenant = await tenantsRepo.updateTenantSettings(ctx.tenantId, body);
    return NextResponse.json({ tenant });
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}
