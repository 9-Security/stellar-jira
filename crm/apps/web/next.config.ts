import type { NextConfig } from 'next';
import { loadEnvConfig } from '@next/env';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const monorepoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
loadEnvConfig(monorepoRoot);

const nextConfig: NextConfig = {
  transpilePackages: ['@crm/db', '@crm/shared'],
  serverExternalPackages: ['@prisma/client'],
  poweredByHeader: false,
};

export default nextConfig;
