import { config } from 'dotenv';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
config({ path: resolve(root, '.env') });
config({ path: resolve(root, '.env.test') });

if (!process.env.DATABASE_URL) {
  throw new Error('DATABASE_URL is required for tests');
}

if (!process.env.AUTH_SECRET) {
  process.env.AUTH_SECRET = 'test-secret-test-secret-test-secret-32';
}
