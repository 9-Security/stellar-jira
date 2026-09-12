import { describe, expect, it } from 'vitest';
import { pingDatabase } from '@crm/db';

describe('health', () => {
  it('pings postgres', async () => {
    await expect(pingDatabase()).resolves.toBe(true);
  });
});
