export class TenantIsolationError extends Error {
  constructor(message = 'Cross-tenant access denied') {
    super(message);
    this.name = 'TenantIsolationError';
  }
}

export class NotFoundError extends Error {
  constructor(message = 'Not found') {
    super(message);
    this.name = 'NotFoundError';
  }
}

export class ForbiddenError extends Error {
  constructor(message = 'Forbidden') {
    super(message);
    this.name = 'ForbiddenError';
  }
}

export class InviteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InviteError';
  }
}

/** tenantId is required — never optional — to prevent unscoped queries. */
export function requireTenantId(tenantId: string): string {
  if (!tenantId || tenantId.trim() === '') {
    throw new TenantIsolationError('tenant_id is required');
  }
  return tenantId;
}
