import { cookies } from 'next/headers';
import { TENANT_COOKIE } from '@/lib/tenant';

export async function setTenantCookie(tenantId: string) {
  const jar = await cookies();
  jar.set(TENANT_COOKIE, tenantId, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    secure: process.env.NODE_ENV === 'production',
    maxAge: 60 * 60 * 24 * 365,
  });
}
