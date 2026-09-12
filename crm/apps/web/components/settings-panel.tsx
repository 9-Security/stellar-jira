'use client';

import { FormEvent, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ROLE_LABELS, ROLES, type Role } from '@crm/shared';
import { PageHeader } from '@/components/app-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

type Member = {
  id: string;
  role: Role;
  status: string;
  user: { email: string; name: string | null };
};

type Invite = {
  id: string;
  email: string;
  role: Role;
  acceptedAt: string | null;
  expiresAt: string;
  createdAt: string;
};

export function SettingsPanel() {
  const qc = useQueryClient();
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const res = await fetch('/api/tenants');
      if (!res.ok) throw new Error('failed');
      return res.json() as Promise<{
        tenant: { name: string; timezone: string };
        members: Member[];
        invites: Invite[];
      }>;
    },
  });

  async function saveTenant(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const res = await fetch('/api/tenants', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.get('name'),
        timezone: form.get('timezone'),
      }),
    });
    if (!res.ok) {
      toast.error('無法儲存租戶設定');
      return;
    }
    toast.success('已儲存');
    await qc.invalidateQueries({ queryKey: ['settings'] });
  }

  async function invite(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const res = await fetch('/api/invites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: form.get('email'),
        role: form.get('role'),
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast.error(body.error ?? '邀請失敗');
      return;
    }
    setInviteUrl(body.inviteUrl);
    toast.success('已建立邀請（郵件為 stub，請複製連結）');
    (e.target as HTMLFormElement).reset();
    await qc.invalidateQueries({ queryKey: ['settings'] });
  }

  async function changeRole(membershipId: string, role: Role) {
    const res = await fetch(`/api/tenants/members/${membershipId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
    if (!res.ok) {
      toast.error('無法變更角色');
      return;
    }
    toast.success('角色已更新');
    await qc.invalidateQueries({ queryKey: ['settings'] });
  }

  if (!settings.data) {
    return <p className="text-sm text-slate-500">載入設定…</p>;
  }

  const { tenant, members, invites } = settings.data;

  return (
    <div className="space-y-6">
      <PageHeader title="設定" description="公司／時區、成員與邀請" />
      <Card>
        <CardHeader>
          <h2 className="font-semibold">租戶資料</h2>
        </CardHeader>
        <CardBody>
          <form onSubmit={saveTenant} className="grid max-w-lg gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="name">名稱</Label>
              <Input id="name" name="name" defaultValue={tenant.name} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="timezone">時區</Label>
              <Input
                id="timezone"
                name="timezone"
                defaultValue={tenant.timezone}
                required
              />
            </div>
            <Button type="submit" className="w-fit">
              儲存
            </Button>
          </form>
          <p className="mt-4 text-xs text-slate-400">方案資訊（佔位）— MVP 不計費</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">成員</h2>
        </CardHeader>
        <CardBody className="space-y-3">
          {members.map((m) => (
            <div
              key={m.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2"
            >
              <div>
                <div className="text-sm font-medium">{m.user.name || m.user.email}</div>
                <div className="text-xs text-slate-500">{m.user.email}</div>
              </div>
              <select
                className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm"
                defaultValue={m.role}
                onChange={(e) => changeRole(m.id, e.target.value as Role)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">邀請成員</h2>
        </CardHeader>
        <CardBody>
          <form onSubmit={invite} className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input name="email" type="email" required />
            </div>
            <div className="space-y-1.5">
              <Label>角色</Label>
              <select
                name="role"
                className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm"
                defaultValue="sales"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
            <Button type="submit">送出邀請</Button>
          </form>
          {inviteUrl ? (
            <p className="mt-3 break-all rounded-lg bg-accent-50 px-3 py-2 text-sm text-accent-600">
              邀請連結（console stub）：{inviteUrl}
            </p>
          ) : null}
          <div className="mt-4 space-y-2">
            {invites.length === 0 ? (
              <p className="text-sm text-slate-500">尚無邀請。</p>
            ) : (
              invites.map((inv) => (
                <div key={inv.id} className="flex items-center justify-between text-sm">
                  <span>
                    {inv.email} · {ROLE_LABELS[inv.role]}
                  </span>
                  <Badge>
                    {inv.acceptedAt
                      ? '已接受'
                      : new Date(inv.expiresAt) < new Date()
                        ? '已過期'
                        : '待接受'}
                  </Badge>
                </div>
              ))
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
