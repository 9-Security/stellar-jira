import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { config } from 'dotenv';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const envFile = resolve(root, '.env');
if (existsSync(envFile)) {
  config({ path: envFile });
}

const args = process.argv.slice(2);
const child = spawn('next', args, {
  stdio: 'inherit',
  env: process.env,
  cwd: resolve(root, 'apps/web'),
  shell: true,
});

child.on('exit', (code) => {
  process.exit(code ?? 0);
});
