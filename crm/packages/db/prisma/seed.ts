import { config } from 'dotenv';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { hash } from 'bcryptjs';
import { PrismaClient } from '../src/generated/client';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
config({ path: resolve(root, '.env') });

const prisma = new PrismaClient();
const PASSWORD = 'Password123!';

async function upsertUser(email: string, name: string, passwordHash: string) {
  return prisma.user.upsert({
    where: { email },
    update: { name, passwordHash },
    create: { email, name, passwordHash },
  });
}

async function main() {
  if (process.env.SEED_ENABLED === 'false') {
    console.log('SEED_ENABLED=false; skipping seed.');
    return;
  }

  const passwordHash = await hash(PASSWORD, 12);

  const acme = await prisma.tenant.upsert({
    where: { slug: 'acme' },
    update: { name: 'Acme 股份有限公司' },
    create: { name: 'Acme 股份有限公司', slug: 'acme', timezone: 'Asia/Taipei' },
  });
  const beta = await prisma.tenant.upsert({
    where: { slug: 'beta' },
    update: { name: 'Beta 科技' },
    create: { name: 'Beta 科技', slug: 'beta', timezone: 'Asia/Taipei' },
  });

  const admin = await upsertUser('admin@acme.test', 'Acme 管理員', passwordHash);
  const sales = await upsertUser('sales@acme.test', '林業務', passwordHash);
  const support = await upsertUser('support@acme.test', '陳客服', passwordHash);
  const eng = await upsertUser('engineering@acme.test', '黃工程', passwordHash);
  const betaAdmin = await upsertUser('admin@beta.test', 'Beta 管理員', passwordHash);
  const multi = await upsertUser('multi@demo.test', '跨租戶示範', passwordHash);

  async function member(
    tenantId: string,
    userId: string,
    role: 'admin' | 'sales' | 'support' | 'engineering',
  ) {
    return prisma.membership.upsert({
      where: { tenantId_userId: { tenantId, userId } },
      update: { role, status: 'active' },
      create: { tenantId, userId, role, status: 'active' },
    });
  }

  const acmeAdmin = await member(acme.id, admin.id, 'admin');
  await member(acme.id, sales.id, 'sales');
  await member(acme.id, support.id, 'support');
  await member(acme.id, eng.id, 'engineering');
  await member(beta.id, betaAdmin.id, 'admin');
  await member(acme.id, multi.id, 'admin');
  await member(beta.id, multi.id, 'sales');

  const tenantIds = { in: [acme.id, beta.id] };
  await prisma.ticketScheduleLink.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.statusEvent.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.activity.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.opportunity.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.ticketComment.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.ticket.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.schedule.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.contact.deleteMany({ where: { tenantId: tenantIds } });
  await prisma.company.deleteMany({ where: { tenantId: tenantIds } });

  const north = await prisma.company.create({
    data: {
      tenantId: acme.id,
      name: '北極星零售',
      website: 'https://northstar.example',
      phone: '02-5555-0101',
      notes: '種子客戶（Acme）',
      ownerMembershipId: acmeAdmin.id,
    },
  });
  await prisma.company.create({
    data: {
      tenantId: acme.id,
      name: '南島物流',
      website: 'https://south-logistics.example',
      phone: '07-5555-0202',
      notes: '第二間示範公司',
      ownerMembershipId: acmeAdmin.id,
    },
  });
  await prisma.company.create({
    data: {
      tenantId: beta.id,
      name: 'Beta 內部客戶（不應被 Acme 看見）',
      notes: '隔離測試用',
    },
  });

  const ticket = await prisma.ticket.create({
    data: {
      tenantId: acme.id,
      title: '門市 POS 異常',
      description: '種子工單',
      status: 'open',
      priority: 'high',
      companyId: north.id,
      assigneeMembershipId: acmeAdmin.id,
    },
  });
  await prisma.ticket.create({
    data: {
      tenantId: acme.id,
      title: '帳號開通申請',
      status: 'in_progress',
      priority: 'medium',
      companyId: north.id,
    },
  });

  const start = new Date();
  start.setDate(start.getDate() + 1);
  start.setHours(10, 0, 0, 0);
  const end = new Date(start);
  end.setHours(11, 30, 0, 0);

  const schedule = await prisma.schedule.create({
    data: {
      tenantId: acme.id,
      title: '北極星現場勘查',
      type: 'field_work',
      status: 'scheduled',
      startAt: start,
      endAt: end,
      assigneeMembershipId: acmeAdmin.id,
    },
  });

  await prisma.ticketScheduleLink.create({
    data: {
      tenantId: acme.id,
      ticketId: ticket.id,
      scheduleId: schedule.id,
    },
  });

  await prisma.opportunity.create({
    data: {
      tenantId: acme.id,
      title: '北極星年度維護',
      amount: 480000,
      stage: 'negotiating',
      companyId: north.id,
      ownerMembershipId: acmeAdmin.id,
    },
  });

  console.log('Seed complete.');
  console.log('  Acme admin:       admin@acme.test / Password123!');
  console.log('  Acme sales:       sales@acme.test / Password123!');
  console.log('  Acme support:     support@acme.test / Password123!');
  console.log('  Acme engineering: engineering@acme.test / Password123!');
  console.log('  Beta admin:       admin@beta.test / Password123!');
  console.log('  Multi-tenant:     multi@demo.test / Password123!');
}

main()
  .catch((err) => {
    console.error(err);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
