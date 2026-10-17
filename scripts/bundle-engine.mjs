import { spawnSync } from 'node:child_process';
import { mkdirSync, copyFileSync, chmodSync } from 'node:fs';
import { resolve } from 'node:path';
import { root, python, env } from './engine-env.mjs';
function run(command, args) {
  const r = spawnSync(command, args, { cwd: root, env, stdio: 'inherit' });
  if (r.status !== 0) process.exit(r.status ?? 1);
}
const triple = spawnSync('rustc', ['--print', 'host-tuple'], { env, encoding: 'utf8' });
if (triple.status !== 0) throw new Error('Rust is required. Install rustup, then retry.');
run(python, [
  '-m',
  'PyInstaller',
  '--noconfirm',
  '--clean',
  '--onefile',
  '--name',
  'narravo-engine',
  '--collect-all',
  'narravo_engine',
  '--collect-all',
  'alembic',
  '--hidden-import',
  'sqlalchemy.dialects.sqlite',
  '--distpath',
  '.build-tools/sidecar',
  '--workpath',
  '.build-tools/pyinstaller',
  '--specpath',
  '.build-tools',
  'scripts/engine-entry.py',
]);
const folder = resolve(root, 'apps/desktop/src-tauri/binaries');
mkdirSync(folder, { recursive: true });
const ext = process.platform === 'win32' ? '.exe' : '';
const dest = resolve(folder, `narravo-engine-${triple.stdout.trim()}${ext}`);
copyFileSync(resolve(root, `.build-tools/sidecar/narravo-engine${ext}`), dest);
chmodSync(dest, 0o755);
console.log('Bundled engine for ' + triple.stdout.trim());
