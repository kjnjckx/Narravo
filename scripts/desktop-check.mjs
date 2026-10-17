import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { root, env } from './engine-env.mjs';
for (const args of [
  ['fmt', '--check'],
  ['clippy', '--all-targets', '--', '-D', 'warnings'],
  ['test'],
]) {
  const result = spawnSync('cargo', args, {
    cwd: resolve(root, 'apps/desktop/src-tauri'),
    env,
    stdio: 'inherit',
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}
