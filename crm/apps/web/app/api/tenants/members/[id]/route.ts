import { NextResponse } from 'next/server';
import { z } from 'zod';
import { ROLES } from '@crm/shared';
import { canAccessSettings } from '@crm/shared';
import { ForbiddenError, tenantsRepo } from '@crm/db';
import { apiError, loadApiTenant } from '@/lib/api';

const schema = z.object({
  role: z.enum(ROLES),
});

export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const tenant = await loadApiTenant();
    if (!canAccessSettings(tenant.role)) {
      throw new ForbiddenError('Admin only');
    }
    const { id } = await ctx.params;
    const body = schema.parse(await req.json());
    const membership = await tenantsRepo.updateMemberRole(tenant.tenantId, id, body.role);
    if (!membership) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    return NextResponse.json({ membership });
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}
