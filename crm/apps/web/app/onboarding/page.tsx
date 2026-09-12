'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function OnboardingPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    const form = new FormData(e.currentTarget);
    const res = await fetch('/api/tenants', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: String(form.get('name') ?? '') }),
    });
    const body = await res.json().catch(() => ({}));
    setPending(false);
    if (!res.ok) {
      setError(body.error ?? '無法建立租戶');
      return;
    }
    router.push('/');
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-card">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
          Nine CRM
        </div>
        <h1 className="mt-2 text-xl font-semibold">建立你的租戶</h1>
        <p className="mt-1 text-sm text-slate-500">
          你尚未加入任何租戶。建立後你會成為管理員。
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">租戶／公司名稱</Label>
            <Input id="name" name="name" required />
          </div>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <Button className="w-full" disabled={pending}>
            {pending ? '建立中…' : '建立租戶'}
          </Button>
        </form>
      </div>
    </div>
  );
}
