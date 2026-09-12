'use client';

import { FormEvent, use, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

export default function CompanyDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const query = useQuery({
    queryKey: ['company', id],
    queryFn: async () => {
      const res = await fetch(`/api/companies/${id}`);
      if (res.status === 404) throw new Error('not-found');
      if (!res.ok) throw new Error('failed');
      return res.json() as Promise<{
        company: {
          id: string;
          name: string;
          website: string | null;
          phone: string | null;
          notes: string | null;
        };
        canWrite: boolean;
      }>;
    },
  });

  if (query.isError) {
    return <p className="text-sm text-slate-600">找不到這間公司（或你沒有權限查看）。</p>;
  }
  if (!query.data) {
    return <p className="text-sm text-slate-500">載入中…</p>;
  }

  const { company, canWrite } = query.data;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canWrite) return;
    setPending(true);
    const form = new FormData(e.currentTarget);
    const res = await fetch(`/api/companies/${id}`, {
      method: 'PATCH',
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
      setError(body.error ?? '儲存失敗');
      return;
    }
    await qc.invalidateQueries({ queryKey: ['company', id] });
    await qc.invalidateQueries({ queryKey: ['companies'] });
    router.refresh();
  }

  async function onDelete() {
    setPending(true);
    const res = await fetch(`/api/companies/${id}`, { method: 'DELETE' });
    setPending(false);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(body.error ?? '無法刪除');
      return;
    }
    router.push('/companies');
    router.refresh();
  }

  return (
    <div>
      <PageHeader
        title={company.name}
        description="公司詳情 · 聯絡人／商機關聯於後續 Sprint"
      />
      <Card className="max-w-xl">
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="name">公司名稱</Label>
              <Input
                id="name"
                name="name"
                defaultValue={company.name}
                disabled={!canWrite}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="website">網站</Label>
              <Input
                id="website"
                name="website"
                defaultValue={company.website ?? ''}
                disabled={!canWrite}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="phone">電話</Label>
              <Input
                id="phone"
                name="phone"
                defaultValue={company.phone ?? ''}
                disabled={!canWrite}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="notes">備註</Label>
              <Textarea
                id="notes"
                name="notes"
                defaultValue={company.notes ?? ''}
                disabled={!canWrite}
              />
            </div>
            {error ? <p className="text-sm text-red-600">{error}</p> : null}
            {canWrite ? (
              <div className="flex flex-wrap gap-2">
                <Button disabled={pending}>{pending ? '儲存中…' : '儲存'}</Button>
                {!confirming ? (
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() => setConfirming(true)}
                  >
                    刪除公司
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="danger"
                    disabled={pending}
                    onClick={onDelete}
                  >
                    確認刪除（軟刪）
                  </Button>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500">你的角色為唯讀，無法編輯或刪除。</p>
            )}
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
