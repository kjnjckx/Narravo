import { existsSync } from 'node:fs';
import { resolve, delimiter } from 'node:path';
export const root = resolve(import.meta.dirname, '..');
export const python = resolve(
  root,
  'services/engine/.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
export const env = {
  ...process.env,
  PYINSTALLER_CONFIG_DIR: resolve(root, '.build-tools/pyinstaller-cache'),
  UV_CACHE_DIR: resolve(root, '.build-tools/uv-cache'),
  UV_PYTHON_INSTALL_DIR: resolve(root, '.build-tools/python'),
};
const localCargo = resolve(root, '.build-tools/cargo');
if (existsSync(localCargo)) {
  env.CARGO_HOME = localCargo;
  env.RUSTUP_HOME = resolve(root, '.build-tools/rustup');
  env.PATH = resolve(localCargo, 'bin') + delimiter + env.PATH;
}
