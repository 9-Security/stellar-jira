import { NextResponse } from 'next/server';
import { pingDatabase } from '@crm/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  const db = await pingDatabase();
  return NextResponse.json({ ok: db, db }, { status: db ? 200 : 503 });
}
