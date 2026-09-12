import { NextResponse } from 'next/server';
import { invitesRepo } from '@crm/db';
import { apiError } from '@/lib/api';
import { getSessionUser } from '@/lib/tenant';
import { setTenantCookie } from '@/lib/tenant-cookie';
import { logRequest } from '@/lib/log';

type Ctx = { params: Promise<{ token: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const { token } = await ctx.params;
    const invite = await invitesRepo.getInviteByRawToken(token);
    if (!invite) {
      return NextResponse.json({ error: 'Invite not found' }, { status: 404 });
    }
    return NextResponse.json({
      tenantName: invite.tenant.name,
      email: invite.email,
      role: invite.role,
      expired: invite.expiresAt.getTime() < Date.now(),
      used: Boolean(invite.acceptedAt),
    });
  } catch (err) {
    return apiError(err);
  }
}

export async function POST(req: Request, ctx: Ctx) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const user = await getSessionUser();
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const { token } = await ctx.params;
    const accepted = await invitesRepo.acceptInvite(token, user.id);
    await setTenantCookie(accepted.membership.tenantId);
    logRequest({
      requestId,
      message: 'invite.accepted',
      tenant_id: accepted.membership.tenantId,
      user_id: user.id,
    });
    return NextResponse.json({
      tenant: accepted.tenant,
      membership: accepted.membership,
    });
  } catch (err) {
    return apiError(err, { requestId });
  }
}
