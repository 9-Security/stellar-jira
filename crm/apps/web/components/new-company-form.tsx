'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

export function NewCompanyForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    const form = new FormData(e.currentTarget);
    const res = await fetch('/api/companies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.get('name'),
        website: form.get('website'),
        phone: form.get('phone'),
        notes: form.get('notes'),
      }),
    });
    const body = await res.json().catch(() => ({}));
    setPending(false);
    if (!res.ok) {
      setError(body.error ?? '無法建立');
      return;
    }
    router.push(`/companies/${body.company.id}`);
    router.refresh();
  }

  return (
    <div>
      <PageHeader title="新建公司" description="僅管理員與業務可寫入" />
      <Card className="max-w-xl">
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="name">公司名稱</Label>
              <Input id="name" name="name" required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="website">網站</Label>
              <Input id="website" name="website" placeholder="https://" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="phone">電話</Label>
              <Input id="phone" name="phone" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="notes">備註</Label>
              <Textarea id="notes" name="notes" />
            </div>
            {error ? <p className="text-sm text-red-600">{error}</p> : null}
            <div className="flex gap-2">
              <Button disabled={pending}>{pending ? '儲存中…' : '建立'}</Button>
              <Button type="button" variant="outline" onClick={() => router.back()}>
                取消
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
