'use client';

import { FormEvent, useEffect, useState } from 'react';
import { signIn, useSession } from 'next-auth/react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ROLE_LABELS, type Role } from '@crm/shared';

type InviteInfo = {
  tenantName: string;
  email: string;
  role: Role;
  expired: boolean;
  used: boolean;
};

export default function InvitePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const { data: session, status } = useSession();
  const router = useRouter();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    fetch(`/api/invites/${token}`)
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error ?? '邀請無效');
        setInfo(body);
      })
      .catch((e: Error) => setError(e.message));
  }, [token]);

  async function accept() {
    setPending(true);
    setError(null);
    const res = await fetch(`/api/invites/${token}`, { method: 'POST' });
    const body = await res.json().catch(() => ({}));
    setPending(false);
    if (!res.ok) {
      setError(body.error ?? '無法接受邀請');
      return;
    }
    router.push('/');
    router.refresh();
  }

  async function registerAndAccept(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get('email') ?? info?.email ?? '');
    const password = String(form.get('password') ?? '');
    const name = String(form.get('name') ?? '');
    setPending(true);
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setPending(false);
      setError(body.error ?? '註冊失敗');
      return;
    }
    const sign = await signIn('credentials', { email, password, redirect: false });
    if (!sign || sign.error) {
      setPending(false);
      setError('請改從登入頁進入後再開邀請連結');
      return;
    }
    await accept();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-card">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
          Nine CRM
        </div>
        <h1 className="mt-2 text-xl font-semibold">接受邀請</h1>
        {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}
        {!info ? (
          <p className="mt-3 text-sm text-slate-500">載入邀請…</p>
        ) : info.used || info.expired ? (
          <p className="mt-3 text-sm text-slate-600">
            此邀請{info.used ? '已使用' : '已過期'}。請向管理員索取新邀請。
          </p>
        ) : (
          <>
            <p className="mt-3 text-sm text-slate-600">
              加入 <strong>{info.tenantName}</strong>，角色 {ROLE_LABELS[info.role]}（
              {info.email}）
            </p>
            {status === 'authenticated' && session?.user?.email === info.email ? (
              <Button className="mt-6 w-full" onClick={accept} disabled={pending}>
                {pending ? '加入中…' : '接受邀請'}
              </Button>
            ) : status === 'authenticated' ? (
              <p className="mt-4 text-sm text-amber-700">
                目前登入帳號與邀請 Email 不符。請改用 {info.email} 登入。
              </p>
            ) : (
              <form onSubmit={registerAndAccept} className="mt-5 space-y-3">
                <p className="text-sm text-slate-500">
                  還沒有帳號？用邀請 Email 註冊後會自動加入。
                </p>
                <div className="space-y-1.5">
                  <Label>姓名</Label>
                  <Input name="name" required />
                </div>
                <div className="space-y-1.5">
                  <Label>Email</Label>
                  <Input name="email" type="email" defaultValue={info.email} required />
                </div>
                <div className="space-y-1.5">
                  <Label>密碼</Label>
                  <Input name="password" type="password" minLength={8} required />
                </div>
                <Button className="w-full" disabled={pending}>
                  {pending ? '處理中…' : '註冊並加入'}
                </Button>
                <p className="text-center text-sm text-slate-500">
                  已有帳號？{' '}
                  <Link
                    href={`/login?from=/invites/${token}`}
                    className="font-medium text-accent"
                  >
                    登入
                  </Link>
                </p>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
}
