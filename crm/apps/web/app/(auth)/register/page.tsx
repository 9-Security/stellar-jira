'use client';

import { FormEvent, useState } from 'react';
import { signIn } from 'next-auth/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    const payload = {
      name: String(form.get('name') ?? ''),
      email: String(form.get('email') ?? ''),
      password: String(form.get('password') ?? ''),
      tenantName: String(form.get('tenantName') ?? ''),
    };
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      setPending(false);
      setError(body.error ?? '註冊失敗');
      return;
    }
    const sign = await signIn('credentials', {
      email: payload.email,
      password: payload.password,
      redirect: false,
    });
    setPending(false);
    if (!sign || sign.error) {
      setError('註冊成功但登入失敗，請改走登入頁');
      return;
    }
    router.push('/');
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-card">
        <div className="mb-6">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
            Nine CRM
          </div>
          <h1 className="mt-2 text-xl font-semibold text-slate-900">建立帳號與租戶</h1>
          <p className="mt-1 text-sm text-slate-500">首位使用者會成為該租戶管理員</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">你的姓名</Label>
            <Input id="name" name="name" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" name="email" type="email" required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">密碼（至少 8 碼）</Label>
            <Input id="password" name="password" type="password" minLength={8} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tenantName">公司／租戶名稱</Label>
            <Input id="tenantName" name="tenantName" required />
          </div>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <Button className="w-full" disabled={pending}>
            {pending ? '建立中…' : '註冊'}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-slate-500">
          已有帳號？{' '}
          <Link href="/login" className="font-medium text-accent hover:underline">
            登入
          </Link>
        </p>
      </div>
    </div>
  );
}
