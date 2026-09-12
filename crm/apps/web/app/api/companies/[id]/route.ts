import { NextResponse } from 'next/server';
import { companiesRepo } from '@crm/db';
import { z } from 'zod';
import { apiError, loadApiTenant } from '@/lib/api';
import { logRequest } from '@/lib/log';
import { canWriteCompanies } from '@crm/shared';

const patchSchema = z.object({
  name: z.string().min(1).optional(),
  website: z.string().optional().nullable(),
  phone: z.string().optional().nullable(),
  notes: z.string().optional().nullable(),
  ownerMembershipId: z.string().optional().nullable(),
});

type Ctx = { params: Promise<{ id: string }> };

export async function GET(req: Request, ctx: Ctx) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const tenant = await loadApiTenant();
    const { id } = await ctx.params;
    const company = await companiesRepo.getCompanyOrThrow(tenant.tenantId, id);
    logRequest({
      requestId,
      message: 'companies.get',
      tenant_id: tenant.tenantId,
      user_id: tenant.userId,
    });
    return NextResponse.json({ company, canWrite: canWriteCompanies(tenant.role) });
  } catch (err) {
    return apiError(err, { requestId });
  }
}

export async function PATCH(req: Request, ctx: Ctx) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const tenant = await loadApiTenant();
    const { id } = await ctx.params;
    const body = patchSchema.parse(await req.json());
    const company = await companiesRepo.updateCompany(
      tenant.tenantId,
      tenant.role,
      id,
      body,
    );
    logRequest({
      requestId,
      message: 'companies.patch',
      tenant_id: tenant.tenantId,
      user_id: tenant.userId,
    });
    return NextResponse.json({ company });
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}

export async function DELETE(req: Request, ctx: Ctx) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const tenant = await loadApiTenant();
    const { id } = await ctx.params;
    await companiesRepo.softDeleteCompany(tenant.tenantId, tenant.role, id);
    logRequest({
      requestId,
      message: 'companies.delete',
      tenant_id: tenant.tenantId,
      user_id: tenant.userId,
    });
    return NextResponse.json({ ok: true });
  } catch (err) {
    return apiError(err, { requestId });
  }
}
