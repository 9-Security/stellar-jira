import { createHash, randomBytes } from 'node:crypto';
import type { Role } from '@crm/shared';
import { ROLES } from '@crm/shared';
import { prisma } from '../client';
import { InviteError, requireTenantId } from '../errors';

const INVITE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export function hashInviteToken(rawToken: string): string {
  return createHash('sha256').update(rawToken).digest('hex');
}

export function generateInviteToken(): { raw: string; hash: string } {
  const raw = randomBytes(32).toString('hex');
  return { raw, hash: hashInviteToken(raw) };
}

export async function createInvite(params: {
  tenantId: string;
  email: string;
  role: Role;
  createdByMembershipId: string;
}) {
  requireTenantId(params.tenantId);
  const email = params.email.trim().toLowerCase();
  if (!email.includes('@')) {
    throw new InviteError('Invalid email');
  }
  if (!ROLES.includes(params.role)) {
    throw new InviteError('Invalid role');
  }

  const membership = await prisma.membership.findFirst({
    where: {
      id: params.createdByMembershipId,
      tenantId: params.tenantId,
      status: 'active',
    },
  });
  if (!membership) {
    throw new InviteError('Creator membership not in tenant');
  }

  const { raw, hash } = generateInviteToken();
  const invite = await prisma.invite.create({
    data: {
      tenantId: params.tenantId,
      email,
      role: params.role,
      tokenHash: hash,
      expiresAt: new Date(Date.now() + INVITE_TTL_MS),
      createdByMembershipId: params.createdByMembershipId,
    },
  });

  return { invite, rawToken: raw };
}

export async function getInviteByRawToken(rawToken: string) {
  const tokenHash = hashInviteToken(rawToken);
  return prisma.invite.findUnique({
    where: { tokenHash },
    include: { tenant: true },
  });
}

export async function acceptInvite(rawToken: string, userId: string) {
  const invite = await getInviteByRawToken(rawToken);
  if (!invite) {
    throw new InviteError('Invite not found');
  }
  if (invite.acceptedAt) {
    throw new InviteError('Invite already used');
  }
  if (invite.expiresAt.getTime() < Date.now()) {
    throw new InviteError('Invite expired');
  }

  const user = await prisma.user.findUnique({ where: { id: userId } });
  if (!user) {
    throw new InviteError('User not found');
  }
  if (user.email.toLowerCase() !== invite.email.toLowerCase()) {
    throw new InviteError('Invite email does not match this account');
  }

  const existing = await prisma.membership.findUnique({
    where: { tenantId_userId: { tenantId: invite.tenantId, userId } },
  });
  if (existing) {
    throw new InviteError('Already a member of this tenant');
  }

  const [membership] = await prisma.$transaction([
    prisma.membership.create({
      data: {
        tenantId: invite.tenantId,
        userId,
        role: invite.role,
        status: 'active',
      },
    }),
    prisma.invite.update({
      where: { id: invite.id },
      data: { acceptedAt: new Date() },
    }),
  ]);

  return { membership, tenant: invite.tenant };
}

export async function listInvites(tenantId: string) {
  requireTenantId(tenantId);
  return prisma.invite.findMany({
    where: { tenantId },
    orderBy: { createdAt: 'desc' },
    include: {
      createdBy: { select: { user: { select: { email: true, name: true } } } },
    },
  });
}
