import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { env, root } from './engine-env.mjs';
const build = process.argv[2] === 'build';
const triple = spawnSync('rustc', ['--print', 'host-tuple'], { env, encoding: 'utf8' });
if (triple.status !== 0) throw new Error('Rust is required. Install rustup, then retry.');
const extension = process.platform === 'win32' ? '.exe' : '';
const binary = resolve(
  root,
  `apps/desktop/src-tauri/binaries/narravo-engine-${triple.stdout.trim()}${extension}`,
);
if (build || !existsSync(binary)) {
  const result = spawnSync(process.execPath, ['scripts/bundle-engine.mjs'], {
    cwd: root,
    env,
    stdio: 'inherit',
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const child = spawn(
  'pnpm',
  [
    '--filter',
    '@narravo/desktop',
    'tauri',
    build ? 'build' : 'dev',
    ...(build ? ['--bundles', 'app'] : []),
  ],
  { cwd: root, env, stdio: 'inherit' },
);
child.on('exit', (code) => process.exit(code ?? 1));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
