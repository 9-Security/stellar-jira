import { NextResponse } from 'next/server';
import { z } from 'zod';
import { tenantsRepo } from '@crm/db';
import { setTenantCookie } from '@/lib/tenant-cookie';
import { apiError, requestIdFrom } from '@/lib/api';
import { logRequest } from '@/lib/log';

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  name: z.string().optional(),
  tenantName: z.string().optional(),
});

export async function POST(req: Request) {
  const requestId = requestIdFrom(req.headers);
  try {
    const body = schema.parse(await req.json());
    const user = await tenantsRepo.registerUser(body);
    let tenantId: string | null = null;
    if (body.tenantName?.trim()) {
      const created = await tenantsRepo.createTenantForUser({
        userId: user.id,
        name: body.tenantName,
      });
      tenantId = created.tenant.id;
      await setTenantCookie(tenantId);
    }
    logRequest({ requestId, message: 'register', user_id: user.id, tenant_id: tenantId });
    return NextResponse.json({ user: { id: user.id, email: user.email }, tenantId });
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}
