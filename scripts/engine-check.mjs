import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { root, python, env } from './engine-env.mjs';
const lint = process.argv.includes('--lint');
const commands = lint
  ? [
      ['ruff', 'check', '.'],
      ['ruff', 'format', '--check', '.'],
      ['mypy', 'src'],
    ]
  : [['pytest']];
for (const args of commands) {
  const result = spawnSync(python, ['-m', ...args], {
    cwd: resolve(root, 'services/engine'),
    env,
    stdio: 'inherit',
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}
