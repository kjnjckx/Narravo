import { invoke, isTauri } from '@tauri-apps/api/core';
import { z } from 'zod';
import * as validators from '../../../packages/contracts/validators.js';
import methods from '../../../packages/contracts/methods.json';
import type { RpcMethods, FileOperation } from '../../../packages/contracts';

declare global {
  interface Window {
    __NARRAVO_TEST_RPC__?: (method: string, params: unknown) => Promise<unknown>;
  }
}
const envelope = z.object({
  jsonrpc: z.literal('2.0'),
  schema_version: z.literal(1),
  id: z.string().nullable(),
  result: z.unknown().optional(),
  error: z
    .object({ code: z.number(), message: z.string(), data: z.object({ code: z.string() }) })
    .optional(),
});
export const connected = () =>
  isTauri() || (import.meta.env.VITE_TEST_BRIDGE === '1' && !!window.__NARRAVO_TEST_RPC__);
export function unwrap<M extends keyof RpcMethods>(
  method: M,
  raw: unknown,
): RpcMethods[M]['result'] {
  const response = envelope.parse(raw);
  if (response.error) throw new Error(response.error.message);
  const validate = validators[methods[method][1] as keyof typeof validators];
  if (!validate || !validate(response.result))
    throw new Error('本地数据格式不匹配，请更新应用后重新打开。');
  return response.result as RpcMethods[M]['result'];
}
export async function rpc<M extends keyof RpcMethods>(
  method: M,
  params: RpcMethods[M]['params'],
): Promise<RpcMethods[M]['result']> {
  let raw: unknown;
  if (isTauri()) raw = await invoke('engine_rpc', { method, params });
  else if (import.meta.env.VITE_TEST_BRIDGE === '1' && window.__NARRAVO_TEST_RPC__)
    raw = await window.__NARRAVO_TEST_RPC__(method, params);
  else throw new Error('当前是界面预览。请在桌面版中创建与保存作品。');
  return unwrap(method, raw);
}
export async function pickImport(
  encoding: string,
  password: string,
  removePdfMargins: boolean,
): Promise<FileOperation | null> {
  const raw = await invoke('choose_import', { encoding, password, removePdfMargins });
  return raw ? unwrap('file.start_import', raw) : null;
}
export async function pickRestore(): Promise<FileOperation | null> {
  const raw = await invoke('choose_restore');
  return raw ? unwrap('backup.preview_restore', raw) : null;
}
export async function saveBackup(operationId: string): Promise<boolean> {
  return invoke('save_backup', { operationId });
}
export async function exportBook(branchId: string, format: 'txt' | 'md'): Promise<boolean> {
  if (isTauri()) return invoke('save_export', { branchId, format });
  const result = await rpc('book.export', { branch_id: branchId, format });
  const url = URL.createObjectURL(new Blob([result.content], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = result.filename;
  a.click();
  URL.revokeObjectURL(url);
  return true;
}

export async function saveProvider(
  config: import('../../../packages/contracts').ProviderConfig,
  apiKey: string,
) {
  if (isTauri())
    return unwrap(
      'provider.save',
      await invoke('save_provider', { config, apiKey: apiKey || null }),
    );
  // Browser test bridge never receives or persists credentials.
  if (apiKey) throw new Error('密钥只能在桌面版中写入系统凭据库。');
  return rpc('provider.save', { config });
}

export async function clearProviderKey(configId: string) {
  if (!isTauri()) throw new Error('仅桌面版可管理系统凭据。');
  return unwrap('provider.save', await invoke('clear_provider_key', { configId }));
}

export async function exportChat(conversationId: string): Promise<boolean> {
  if (isTauri()) return invoke('save_chat_export', { conversationId });
  const result = await rpc('roleplay.export', { conversation_id: conversationId });
  const url = URL.createObjectURL(new Blob([result.content], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = result.filename;
  link.click();
  URL.revokeObjectURL(url);
  return true;
}
