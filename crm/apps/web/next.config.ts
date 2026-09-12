import type { NextConfig } from 'next';
import { config as loadDotenv } from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const monorepoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
loadDotenv({ path: path.join(monorepoRoot, '.env') });

const nextConfig: NextConfig = {
  transpilePackages: ['@crm/db', '@crm/shared'],
  serverExternalPackages: ['@prisma/client'],
  poweredByHeader: false,
};

export default nextConfig;
