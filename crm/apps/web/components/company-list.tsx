'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { PageHeader } from '@/components/app-shell';
import { EmptyState } from '@/components/empty-state';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

type CompanyRow = {
  id: string;
  name: string;
  website: string | null;
  phone: string | null;
  owner: { user: { name: string | null; email: string } } | null;
  updatedAt: string;
};

const col = createColumnHelper<CompanyRow>();

const columns = [
  col.accessor('name', {
    header: '公司',
    cell: (info) => (
      <Link
        href={`/companies/${info.row.original.id}`}
        className="font-medium text-slate-900 hover:text-accent"
      >
        {info.getValue()}
      </Link>
    ),
  }),
  col.accessor('website', {
    header: '網站',
    cell: (info) => info.getValue() || '—',
  }),
  col.accessor('phone', {
    header: '電話',
    cell: (info) => info.getValue() || '—',
  }),
  col.accessor('owner', {
    header: '負責人',
    cell: (info) => {
      const owner = info.getValue();
      return owner?.user.name || owner?.user.email || '—';
    },
  }),
];

export function CompanyList({ canWrite }: { canWrite: boolean }) {
  const query = useQuery({
    queryKey: ['companies'],
    queryFn: async () => {
      const res = await fetch('/api/companies');
      if (!res.ok) throw new Error('failed');
      return (await res.json()) as { companies: CompanyRow[] };
    },
  });

  const data = query.data?.companies ?? [];
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div>
      <PageHeader
        title="客戶"
        description="公司列表（聯絡人 CRUD 於 Sprint 1）"
        actions={
          canWrite ? (
            <Link href="/companies/new">
              <Button>新建公司</Button>
            </Link>
          ) : (
            <Badge>唯讀</Badge>
          )
        }
      />
      {query.isLoading ? (
        <p className="text-sm text-slate-500">載入中…</p>
      ) : data.length === 0 ? (
        <EmptyState
          title="尚無公司"
          description="建立第一間公司，作為商機與工單的關聯對象。"
          actionHref={canWrite ? '/companies/new' : undefined}
          actionLabel={canWrite ? '新建公司' : undefined}
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => (
                    <th key={h.id} className="px-4 py-3 font-medium">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-t border-slate-100 hover:bg-slate-50/80"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3 text-slate-700">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
