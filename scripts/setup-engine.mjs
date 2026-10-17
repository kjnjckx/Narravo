import { spawnSync } from 'node:child_process';
import { root, env } from './engine-env.mjs';
const result = spawnSync(
  'uv',
  ['sync', '--project', 'services/engine', '--frozen', '--dev', '--python', '3.12'],
  { cwd: root, env, stdio: 'inherit' },
);
process.exit(result.status ?? 1);
