import { NextResponse } from 'next/server';
import { companiesRepo } from '@crm/db';
import { z } from 'zod';
import { apiError, loadApiTenant } from '@/lib/api';
import { logRequest } from '@/lib/log';
import { canWriteCompanies } from '@crm/shared';

const createSchema = z.object({
  name: z.string().min(1),
  website: z.string().optional().nullable(),
  phone: z.string().optional().nullable(),
  notes: z.string().optional().nullable(),
  ownerMembershipId: z.string().optional().nullable(),
});

export async function GET(req: Request) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const ctx = await loadApiTenant();
    const companies = await companiesRepo.listCompanies(ctx.tenantId);
    logRequest({
      requestId,
      message: 'companies.list',
      tenant_id: ctx.tenantId,
      user_id: ctx.userId,
    });
    return NextResponse.json({ companies });
  } catch (err) {
    return apiError(err, { requestId });
  }
}

export async function POST(req: Request) {
  const requestId = req.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const ctx = await loadApiTenant();
    const body = createSchema.parse(await req.json());
    const company = await companiesRepo.createCompany(ctx.tenantId, ctx.role, {
      name: body.name,
      website: body.website,
      phone: body.phone,
      notes: body.notes,
      ownerMembershipId: body.ownerMembershipId,
    });
    logRequest({
      requestId,
      message: 'companies.create',
      tenant_id: ctx.tenantId,
      user_id: ctx.userId,
    });
    return NextResponse.json(
      { company, canWrite: canWriteCompanies(ctx.role) },
      { status: 201 },
    );
  } catch (err) {
    if (err instanceof z.ZodError) {
      return NextResponse.json({ error: 'Invalid input' }, { status: 400 });
    }
    return apiError(err, { requestId });
  }
}
