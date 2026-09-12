'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { signOut } from 'next-auth/react';
import {
  Bell,
  Building2,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  Ticket,
  TrendingUp,
  Users,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { hasPermission, ROLE_LABELS, type Permission, type Role } from '@crm/shared';
import type { TenantContext } from '@/lib/tenant';
import { cn } from '@/lib/utils';
import { ForbiddenToast } from './forbidden-toast';

const NAV: Array<{
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  permission: Permission | null;
}> = [
  { href: '/', label: '首頁', icon: LayoutDashboard, permission: null },
  { href: '/companies', label: '客戶', icon: Building2, permission: 'companies:read' },
  {
    href: '/opportunities',
    label: '商機',
    icon: TrendingUp,
    permission: 'opportunities:read',
  },
  { href: '/tickets', label: '工單', icon: Ticket, permission: 'tickets:read' },
  { href: '/schedules', label: '排程', icon: CalendarDays, permission: 'schedules:read' },
  { href: '/reports', label: '報表', icon: Users, permission: 'reports:read' },
  { href: '/settings', label: '設定', icon: Settings, permission: 'settings:write' },
];

export function AppShell({
  ctx,
  children,
}: {
  ctx: TenantContext;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  const items = useMemo(
    () =>
      NAV.filter((item) => {
        if (item.permission === 'schedules:read') {
          return (
            hasPermission(ctx.role, 'schedules:read') ||
            hasPermission(ctx.role, 'schedules:self')
          );
        }
        return !item.permission || hasPermission(ctx.role, item.permission);
      }),
    [ctx.role],
  );

  async function switchTenant(tenantId: string) {
    if (tenantId === ctx.tenantId) {
      setMenuOpen(false);
      return;
    }
    setSwitching(true);
    const res = await fetch('/api/tenants/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenantId }),
    });
    if (res.ok) {
      setMenuOpen(false);
      router.refresh();
    }
    setSwitching(false);
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <ForbiddenToast />
      <aside className="flex w-60 shrink-0 flex-col bg-ink-950 text-slate-200">
        <div className="border-b border-white/10 px-5 py-5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">
            Nine CRM
          </div>
          <div className="mt-2 truncate text-sm font-medium text-white">
            {ctx.tenantName}
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {items.map((item) => {
            const active =
              item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                  active
                    ? 'bg-white/10 text-white'
                    : 'text-slate-300 hover:bg-white/5 hover:text-white',
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-white/10 p-3 text-[11px] text-slate-500">
          雲端多租戶 · Sprint 0
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-6">
          <div className="flex items-center gap-2 text-slate-400">
            <Search className="h-4 w-4" />
            <span className="text-sm">搜尋客戶與工單（即將推出）</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"
              aria-label="通知"
            >
              <Bell className="h-4 w-4" />
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-100"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-50 text-xs font-semibold text-accent-600">
                  {(ctx.name || ctx.email).slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden text-left text-sm md:block">
                  <span className="block font-medium text-slate-800">
                    {ctx.name || ctx.email}
                  </span>
                  <span className="block text-xs text-slate-500">
                    {ROLE_LABELS[ctx.role as Role]}
                  </span>
                </span>
                <ChevronDown className="h-4 w-4 text-slate-400" />
              </button>
              {menuOpen ? (
                <div className="absolute right-0 z-20 mt-2 w-64 rounded-xl border border-slate-200 bg-white py-2 shadow-card">
                  <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    切換租戶
                  </p>
                  {ctx.memberships.map((m) => (
                    <button
                      key={m.tenantId}
                      type="button"
                      disabled={switching}
                      onClick={() => switchTenant(m.tenantId)}
                      className={cn(
                        'flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50',
                        m.tenantId === ctx.tenantId && 'bg-accent-50 text-accent-600',
                      )}
                    >
                      <span>{m.tenantName}</span>
                      <span className="text-xs text-slate-400">
                        {ROLE_LABELS[m.role]}
                      </span>
                    </button>
                  ))}
                  <div className="my-2 border-t border-slate-100" />
                  <button
                    type="button"
                    onClick={() => signOut({ callbackUrl: '/login' })}
                    className="flex w-full items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    <LogOut className="h-4 w-4" />
                    登出
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description ? (
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        ) : null}
      </div>
      {actions}
    </div>
  );
}

export function HelpHint({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-xs text-slate-500">
      <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {children}
    </p>
  );
}
