import type { Role } from './enums';

export type Permission =
  | 'companies:read'
  | 'companies:write'
  | 'contacts:read'
  | 'contacts:write'
  | 'opportunities:read'
  | 'opportunities:write'
  | 'tickets:read'
  | 'tickets:write'
  | 'schedules:read'
  | 'schedules:write'
  | 'schedules:self'
  | 'reports:read'
  | 'settings:write';

const ALL: Permission[] = [
  'companies:read',
  'companies:write',
  'contacts:read',
  'contacts:write',
  'opportunities:read',
  'opportunities:write',
  'tickets:read',
  'tickets:write',
  'schedules:read',
  'schedules:write',
  'reports:read',
  'settings:write',
];

const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  admin: ALL,
  sales: [
    'companies:read',
    'companies:write',
    'contacts:read',
    'contacts:write',
    'opportunities:read',
    'opportunities:write',
    'tickets:read',
    'schedules:self',
    'reports:read',
  ],
  support: [
    'companies:read',
    'contacts:read',
    'opportunities:read',
    'tickets:read',
    'tickets:write',
    'schedules:read',
    'schedules:write',
    'reports:read',
  ],
  engineering: [
    'companies:read',
    'contacts:read',
    'opportunities:read',
    'tickets:read',
    'tickets:write',
    'schedules:read',
    'schedules:write',
    'reports:read',
  ],
};

export function hasPermission(role: Role, permission: Permission): boolean {
  return ROLE_PERMISSIONS[role]?.includes(permission) ?? false;
}

export function canWriteCompanies(role: Role): boolean {
  return hasPermission(role, 'companies:write');
}

export function canAccessSettings(role: Role): boolean {
  return hasPermission(role, 'settings:write');
}

export const NAV_ITEMS = [
  { href: '/', label: '首頁', permission: null },
  { href: '/companies', label: '客戶', permission: 'companies:read' as const },
  { href: '/opportunities', label: '商機', permission: 'opportunities:read' as const },
  { href: '/tickets', label: '工單', permission: 'tickets:read' as const },
  { href: '/schedules', label: '排程', permission: 'schedules:read' as const },
  { href: '/reports', label: '報表', permission: 'reports:read' as const },
  { href: '/settings', label: '設定', permission: 'settings:write' as const },
] as const;
