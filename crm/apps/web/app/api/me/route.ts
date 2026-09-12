import { NextResponse } from 'next/server';
import { apiError, loadApiTenant } from '@/lib/api';

export async function GET() {
  try {
    const ctx = await loadApiTenant();
    return NextResponse.json({
      user: { id: ctx.userId, email: ctx.email, name: ctx.name },
      tenant: { id: ctx.tenantId, name: ctx.tenantName, slug: ctx.tenantSlug },
      role: ctx.role,
      membershipId: ctx.membershipId,
      memberships: ctx.memberships,
    });
  } catch (err) {
    return apiError(err);
  }
}
