'use client';

import { FormEvent, useState } from 'react';
import { signIn } from 'next-auth/react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    const res = await signIn('credentials', {
      email: String(form.get('email') ?? ''),
      password: String(form.get('password') ?? ''),
      redirect: false,
    });
    setPending(false);
    if (!res || res.error) {
      setError('Email 或密碼不正確');
      return;
    }
    router.push(params.get('from') || '/');
    router.refresh();
  }

  return (
    <AuthCard title="登入 Nine CRM" subtitle="純雲端多租戶 · 客戶不必維運主機">
      <form onSubmit={onSubmit} className="space-y-4">
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field
          label="密碼"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <Button className="w-full" disabled={pending}>
          {pending ? '登入中…' : '登入'}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">
        還沒有帳號？{' '}
        <Link href="/register" className="font-medium text-accent hover:underline">
          註冊並建立租戶
        </Link>
      </p>
    </AuthCard>
  );
}

function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-card">
        <div className="mb-6">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
            Nine CRM
          </div>
          <h1 className="mt-2 text-xl font-semibold text-slate-900">{title}</h1>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field(props: {
  label: string;
  name: string;
  type: string;
  required?: boolean;
  autoComplete?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={props.name}>{props.label}</Label>
      <Input id={props.name} {...props} />
    </div>
  );
}
