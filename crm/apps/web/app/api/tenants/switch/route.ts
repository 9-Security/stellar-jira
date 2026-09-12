import { NextResponse } from 'next/server';
import { z } from 'zod';
import { tenantsRepo } from '@crm/db';
import { apiError } from '@/lib/api';
import { getSessionUser } from '@/lib/tenant';
import { setTenantCookie } from '@/lib/tenant-cookie';
import { logRequest } from '@/lib/log';

const switchSchema = z.object({ tenantId: z.string().min(1) });

export async function POST(req: Request) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const user = await getSessionUser();
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const body = switchSchema.parse(await req.json());
    const membership = await tenantsRepo.getActiveMembership(user.id, body.tenantId);
    if (!membership) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    await setTenantCookie(body.tenantId);
    logRequest({
      requestId,
      message: 'tenants.switch',
      tenant_id: body.tenantId,
      user_id: user.id,
    });
    return NextResponse.json({ ok: true, tenantId: body.tenantId });
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}
