import { test, expect } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';

let engine: ChildProcessWithoutNullStreams;
let directory: string;
const pending = new Map<
  string,
  { resolve: (value: unknown) => void; reject: (reason: unknown) => void }
>();
let sequence = 0;
async function rpc(method: string, params: unknown): Promise<any> {
  if (
    method === 'provider.test' ||
    method === 'narration.synthesize' ||
    method === 'roleplay.send' ||
    method === 'roleplay.synthesize' ||
    (method === 'writing.generate' && (params as any).provider === 'configured')
  ) {
    const record = await rpc('provider.get', { config_id: (params as any).config_id });
    params = { ...(params as object), _credential_endpoint: record.result.base_url };
  }
  const id = String(++sequence);
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    engine.stdin.write(
      JSON.stringify({ jsonrpc: '2.0', schema_version: 1, id, method, params }) + '\n',
    );
  });
}
test.beforeEach(async ({ page }) => {
  directory = await mkdtemp(resolve(tmpdir(), 'narravo-e2e-'));
  engine = spawn(resolve('services/engine/.venv/bin/python'), [
    resolve('tests/e2e/engine_fixture.py'),
    '--data-dir',
    directory,
  ]);
  createInterface({ input: engine.stdout }).on('line', (line) => {
    const result = JSON.parse(line);
    const request = pending.get(result.id);
    if (request) {
      pending.delete(result.id);
      request.resolve(result);
    }
  });
  engine.on('exit', () => {
    for (const p of pending.values()) p.reject(new Error('engine exited'));
    pending.clear();
  });
  await page.exposeFunction('testEngineRpc', rpc);
  await page.addInitScript(() => {
    (window as any).__NARRAVO_TEST_RPC__ = (window as any).testEngineRpc;
  });
  await page.route('http://127.0.0.1:1421/', async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      headers: {
        ...response.headers(),
        'Content-Security-Policy':
          "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:1421; img-src 'self' data:; media-src 'self' blob:",
      },
    });
  });
  await page.goto('/');
});
test.afterEach(async () => {
  if (!engine) return;
  engine.stdin.end();
  await new Promise<void>((resolve) => engine.once('exit', () => resolve()));
  await rm(directory, { recursive: true, force: true });
});

test('no-model original: create, autosave Unicode, chapters, reopen and export', async ({
  page,
}) => {
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByLabel('作品名称', { exact: true }).fill('雨停之前');
  await page.getByRole('button', { name: '开始创作' }).click();
  const editor = page.getByRole('textbox', { name: '章节正文' });
  await editor.fill('林舟说：“雨停了。😀”');
  await expect(page.getByText('已保存到本地')).toBeVisible();
  await expect
    .poll(async () => {
      const library = await rpc('book.list', {});
      return library.result.books[0].word_count;
    })
    .toBe(11);
  await page.getByRole('button', { name: '新建章节', exact: true }).click();
  await expect(editor).toBeEmpty();
  await editor.fill('第二章的信。');
  await expect(page.getByText('已保存到本地')).toBeVisible();
  await page.getByRole('button', { name: '返回作品库', exact: true }).click();
  await page.reload();
  await page.getByRole('button', { name: /雨停之前.*原创/ }).click();
  await expect(editor).toContainText('林舟说');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: '导出', exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('雨停之前.txt');
  await page.screenshot({ path: '.build-tools/workspace.png' });
});

test('demo stream remains a candidate until edited acceptance and planning conflict is visible', async ({
  page,
}) => {
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByRole('button', { name: '开始创作' }).click();
  await page.getByLabel('本次创作意图').fill('写一个修钟匠的开篇');
  await page.getByRole('button', { name: '生成演示候选' }).click();
  await expect(page.getByLabel('接纳内容（可编辑）')).toBeVisible();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toBeEmpty();
  await page.getByLabel('接纳内容（可编辑）').fill('钟声停了。');
  await page.getByRole('button', { name: '接纳候选', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toContainText('钟声停了。');
  await page.getByLabel('本次创作意图').fill('继续写');
  await page.getByRole('button', { name: '生成演示候选' }).click();
  await expect(page.getByLabel('接纳内容（可编辑）')).toBeVisible();
  await page.getByRole('button', { name: '故事设定', exact: true }).click();
  await page.getByRole('button', { name: '添加第一个设定' }).click();
  await page.getByLabel('标题 / 人物姓名').fill('结局');
  await page.getByLabel('内容', { exact: true }).fill('钟声再次响起');
  await page.getByRole('button', { name: '保存设定' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.getByRole('button', { name: /创作简报.*结局/ })).toBeVisible();
  await page.getByRole('button', { name: '写作助手', exact: true }).click();
  await page.getByRole('button', { name: '接纳候选', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('规划已经改变');
  await expect(page.getByRole('textbox', { name: '章节正文' })).toHaveText('钟声停了。');
});

test('TXT preview precedes library creation and imported text uses same editor', async ({
  page,
}) => {
  await page.getByRole('button', { name: /导入你的小说/ }).click();
  await page.getByLabel('测试导入文件').setInputFiles({
    name: '短篇.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('第一章 雨\n雨停了。\n第二章 门\n门开了。'),
  });
  await expect(page.getByText('utf-8 · 2 章')).toBeVisible();
  expect((await rpc('book.list', {})).result.books).toHaveLength(0);
  await page.getByRole('button', { name: '确认导入' }).click();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toContainText('雨停了。');
  await expect(page.getByText('导入作品', { exact: true })).toBeVisible();
});

test('branch edits can be restored without changing parent and tasks reopen after refresh', async ({
  page,
}) => {
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByRole('button', { name: '开始创作' }).click();
  const editor = page.getByRole('textbox', { name: '章节正文' });
  await editor.fill('父分支的正文');
  await expect(page.getByText('已保存到本地')).toBeVisible();
  await page.getByRole('button', { name: '创建分支', exact: true }).click();
  await page.getByLabel('分支名称').fill('另一种结局');
  await page.getByRole('button', { name: '创建分支', exact: true }).last().click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await editor.fill('另一条路');
  await expect(page.getByText('已保存到本地')).toBeVisible();
  await page.getByRole('button', { name: '版本历史' }).click();
  await page.getByRole('button', { name: '恢复此版本' }).first().click();
  await expect(editor).toHaveText('父分支的正文');
  await page.getByLabel('当前分支').selectOption({ label: '主线' });
  await expect(editor).toHaveText('父分支的正文');
  await page.getByLabel('本次创作意图').fill('写下一个问题');
  await page.getByRole('button', { name: '生成演示候选' }).click();
  await expect(page.getByLabel('接纳内容（可编辑）')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '任务中心', exact: true }).click();
  await page.getByRole('button', { name: /未命名作品.*打开候选/ }).click();
  await expect(page.getByLabel('接纳内容（可编辑）')).toBeVisible();
  await expect(editor).toHaveText('父分支的正文');
});

test('LLM and TTS have independent drafts, keys, saved lists and persistence', async ({ page }) => {
  await page.getByRole('button', { name: '模型设置', exact: true }).click();
  const llm = page.getByRole('tabpanel', { name: '文本模型（LLM）', exact: true });
  const tts = page.getByRole('tabpanel', { name: '语音模型（TTS）', exact: true });
  await expect(llm).toBeVisible();
  await expect(llm.getByLabel('添加服务预设').locator('option[value="openai-tts"]')).toHaveCount(0);
  await expect(llm.getByLabel('接口协议').locator('option[value="openai_speech"]')).toHaveCount(0);
  await expect(llm.getByLabel('音色 ID')).toHaveCount(0);
  await llm.getByLabel('添加服务预设').selectOption('deepseek');
  await llm.getByLabel('配置名称', { exact: true }).fill('独立文本配置');
  await llm.getByLabel('模型 ID', { exact: true }).fill('text-draft');
  await llm.getByLabel('API Key', { exact: true }).fill('draft-only-test-value');
  // Keyboard navigation must preserve the other editor's unsaved fields.
  await page.getByRole('tab', { name: '文本模型（LLM）', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(tts).toBeVisible();
  await expect(tts.getByLabel('配置名称', { exact: true })).toHaveValue('');
  await expect(tts.getByLabel('API Key', { exact: true })).toHaveValue('');
  await expect(tts.getByLabel('添加服务预设').locator('option[value="deepseek"]')).toHaveCount(0);
  await expect(tts.getByLabel('接口协议').locator('option[value="openai_chat"]')).toHaveCount(0);
  await expect(tts.getByLabel('模型上下文上限')).toHaveCount(0);
  await tts.getByLabel('添加服务预设').selectOption('openai-tts');
  await tts.getByLabel('配置名称', { exact: true }).fill('独立语音配置');
  await tts.getByLabel('音色 ID', { exact: true }).fill('alloy');
  await tts.getByText('高级参数与本地服务', { exact: true }).click();
  await tts.getByLabel('此服务需要 API Key', { exact: true }).uncheck();
  await tts.getByRole('button', { name: '保存 TTS 配置', exact: true }).click();
  await expect(tts.getByRole('status')).toContainText('TTS 配置已保存');
  let records = (await rpc('provider.list', {})).result.providers;
  expect(records).toHaveLength(1);
  expect(records[0]).toMatchObject({ kind: 'tts', name: '独立语音配置', voice: 'alloy' });
  const speechRecord = records[0];
  await page.getByRole('tab', { name: '语音模型（TTS）', exact: true }).focus();
  await page.keyboard.press('ArrowLeft');
  await expect(llm.getByLabel('模型 ID', { exact: true })).toHaveValue('text-draft');
  await expect(llm.getByLabel('API Key', { exact: true })).toHaveValue('draft-only-test-value');
  await expect(llm.getByRole('button', { name: /独立语音配置/ })).toHaveCount(0);
  await llm.getByLabel('API Key', { exact: true }).fill('');
  await llm.getByText('高级参数与本地服务', { exact: true }).click();
  await llm.getByLabel('此服务需要 API Key', { exact: true }).uncheck();
  await llm.getByRole('button', { name: '保存 LLM 配置', exact: true }).click();
  await expect(llm.getByRole('status')).toContainText('LLM 配置已保存');
  await llm.getByLabel('模型 ID', { exact: true }).fill('text-updated');
  await llm.getByRole('button', { name: '保存 LLM 配置', exact: true }).click();
  await expect
    .poll(
      async () =>
        (await rpc('provider.list', {})).result.providers.find((p: any) => p.kind === 'llm')?.model,
    )
    .toBe('text-updated');
  records = (await rpc('provider.list', {})).result.providers;
  expect(records).toHaveLength(2);
  expect(records.find((p: any) => p.kind === 'tts')).toEqual(speechRecord);
  expect(new Set(records.map((p: any) => p.id)).size).toBe(2);
  await page.reload();
  await page.getByRole('button', { name: '模型设置', exact: true }).click();
  await llm.getByRole('button', { name: /独立文本配置/ }).click();
  await expect(llm.getByLabel('模型 ID', { exact: true })).toHaveValue('text-updated');
  await page.getByRole('tab', { name: '语音模型（TTS）', exact: true }).click();
  await expect(tts.getByRole('button', { name: /独立文本配置/ })).toHaveCount(0);
  await tts.getByRole('button', { name: /独立语音配置/ }).click();
  await expect(tts.getByLabel('音色 ID', { exact: true })).toHaveValue('alloy');
  await page.screenshot({ path: '.build-tools/separate-tts-settings.png' });
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByRole('button', { name: '开始创作' }).click();
  await page.getByRole('button', { name: '管理 TTS 配置', exact: true }).click();
  await expect(tts).toBeVisible();
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '管理 LLM 配置', exact: true }).click();
  await expect(llm).toBeVisible();
});

test('model settings save then use configured text and speech adapters with cached playback', async ({
  page,
}) => {
  await page.getByRole('button', { name: '模型设置', exact: true }).click();
  const llm = page.getByRole('tabpanel', { name: '文本模型（LLM）', exact: true });
  const tts = page.getByRole('tabpanel', { name: '语音模型（TTS）', exact: true });
  await llm.getByLabel('添加服务预设').selectOption('deepseek');
  await llm.getByLabel('模型 ID', { exact: true }).fill('fixture-model');
  await llm.getByText('高级参数与本地服务', { exact: true }).click();
  await llm.getByLabel('此服务需要 API Key', { exact: true }).uncheck();
  await llm.getByRole('button', { name: '保存 LLM 配置', exact: true }).click();
  await expect(llm.getByRole('status').last()).toContainText('LLM 配置已保存');
  await page.getByLabel('允许外部模型请求').check();
  await llm.getByRole('button', { name: '测试 LLM（可能计费）', exact: true }).click();
  await expect(llm.getByRole('status').last()).toContainText('测试成功');
  await page.getByRole('tab', { name: '语音模型（TTS）', exact: true }).click();
  await tts.getByLabel('添加服务预设').selectOption('openai-tts');
  await tts.getByText('高级参数与本地服务', { exact: true }).click();
  await tts.getByLabel('此服务需要 API Key', { exact: true }).uncheck();
  await tts.getByRole('button', { name: '保存 TTS 配置', exact: true }).click();
  await expect(tts.getByRole('status').first()).toContainText('TTS 配置已保存');
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByRole('button', { name: '开始创作' }).click();
  await page.getByRole('textbox', { name: '章节正文' }).fill('很久以前，有一个国王。');
  await page.getByLabel('本次创作意图').fill('国王发现王冠失踪');
  await page.getByRole('button', { name: '生成候选', exact: true }).click();
  await expect(page.getByLabel('生成候选', { exact: true })).toHaveValue('国王发现王冠失踪了。😀');
  await page.getByRole('button', { name: '接纳候选', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toContainText(
    '国王发现王冠失踪了。😀',
  );
  await page.getByRole('button', { name: '准备本章语音', exact: true }).click();
  await page.getByRole('button', { name: '开始合成（可能计费）', exact: true }).click();
  await expect(page.getByRole('button', { name: '播放语音', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '播放语音', exact: true }).click();
  await expect(page.getByText('语音准备完成；声音由 AI 生成。', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '准备本章语音', exact: true }).click();
  await page.getByRole('button', { name: '开始合成（可能计费）', exact: true }).click();
  await expect(page.getByRole('button', { name: '准备本章语音', exact: true })).toBeVisible();
  await expect(page.getByText(/本次提交 0 次/)).toBeVisible();
  await expect
    .poll(() => page.locator('audio').evaluate((element: HTMLAudioElement) => element.readyState))
    .toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: '.build-tools/providers-workspace.png' });
  await page.getByRole('textbox', { name: '章节正文' }).fill('正文已经改变');
  await expect(page.getByText('正文已修改，此音频基于旧修订，已暂停。')).toBeVisible();
});

test('EPUB uses spine order and PDF requires accepting omitted pages', async ({ page }) => {
  const { execFileSync } = await import('node:child_process');
  const fixture = (expression: string) =>
    execFileSync(resolve('services/engine/.venv/bin/python'), [
      '-c',
      `import sys; sys.path.insert(0, 'services/engine/tests'); from test_files import epub_bytes, pdf_bytes; sys.stdout.buffer.write(${expression})`,
    ]);
  await page.getByRole('button', { name: /导入你的小说/ }).click();
  await page.getByLabel('测试导入文件').setInputFiles({
    name: 'spine.epub',
    mimeType: 'application/epub+zip',
    buffer: fixture('epub_bytes()'),
  });
  await expect(page.getByText('epub · 2 章')).toBeVisible();
  await expect(page.getByLabel('作品名称', { exact: true })).toHaveValue('倒序测试');
  await page.getByRole('button', { name: '确认导入' }).click();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toContainText('雨停了。😀');
  await expect(page.getByRole('textbox', { name: '章节正文' })).not.toContainText('窃取密钥');
  await page.getByRole('button', { name: '返回作品库', exact: true }).click();
  await page.getByRole('button', { name: /导入你的小说/ }).click();
  await page.getByLabel('测试导入文件').setInputFiles({
    name: 'mixed.pdf',
    mimeType: 'application/pdf',
    buffer: fixture('pdf_bytes(mixed=True)'),
  });
  await expect(page.getByText('pdf · 1 章')).toBeVisible();
  await expect(page.getByRole('button', { name: '确认导入' })).toBeDisabled();
  await page.getByRole('checkbox', { name: /我已核对遗漏页码（2）/ }).check();
  await page.getByRole('button', { name: '确认导入' }).click();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toContainText('The door opened.');
});

test('full backup restores original writing, author secrets and history into an independent library', async ({
  page,
}) => {
  const { readFile } = await import('node:fs/promises');
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByLabel('作品名称', { exact: true }).fill('待备份作品');
  await page.getByRole('button', { name: '开始创作' }).click();
  await page.getByRole('textbox', { name: '章节正文' }).fill('原始的雨。😀');
  await expect(page.getByText('已保存到本地')).toBeVisible();
  await page.getByRole('button', { name: '故事设定', exact: true }).click();
  await page.getByRole('button', { name: '添加第一个设定' }).click();
  await page.getByLabel('标题 / 人物姓名').fill('结局秘密');
  await page.getByLabel('内容', { exact: true }).fill('钟表是时间之门。');
  await page.getByRole('button', { name: '保存设定' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('button', { name: '返回作品库', exact: true }).click();
  await page.getByRole('button', { name: '备份与恢复', exact: true }).click();
  await page.getByRole('button', { name: '创建完整备份', exact: true }).click();
  await expect(page.getByText('备份已准备，可保存文件', { exact: true })).toBeVisible();
  const id = await page.evaluate(() => localStorage.getItem('narravo.file-operation'));
  const backup = await readFile(resolve(directory, 'outbox', `${id}.narravo`));
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: /写下一个新世界/ }).click();
  await page.getByLabel('作品名称', { exact: true }).fill('恢复前仍保留的作品');
  await page.getByRole('button', { name: '开始创作' }).click();
  await page.getByRole('button', { name: '返回作品库', exact: true }).click();
  await page.getByRole('button', { name: '备份与恢复', exact: true }).click();
  await page
    .getByLabel('测试恢复文件')
    .setInputFiles({ name: 'saved.narravo', mimeType: 'application/zip', buffer: backup });
  await expect(page.getByText('校验通过，等待恢复为独立书库', { exact: true })).toBeVisible();
  expect((await rpc('book.list', {})).result.books).toHaveLength(2);
  await page.getByRole('button', { name: '恢复为独立书库并切换', exact: true }).click();
  await expect(
    page.getByText('已切换至恢复书库；原书库仍保留在本机', { exact: true }),
  ).toBeVisible();
  expect((await rpc('book.list', {})).result.books).toHaveLength(1);
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: /待备份作品.*原创/ }).click();
  await expect(page.getByRole('textbox', { name: '章节正文' })).toHaveText('原始的雨。😀');
  await page.getByRole('button', { name: '故事设定', exact: true }).click();
  await expect(page.getByRole('button', { name: /创作简报.*结局秘密/ })).toBeVisible();
  await page.getByRole('button', { name: '版本历史' }).click();
  await expect(page.getByRole('button', { name: '恢复此版本' }).first()).toBeVisible();
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '返回作品库', exact: true }).click();
  await page.getByRole('button', { name: '备份与恢复', exact: true }).click();
  await page.getByRole('button', { name: '切回恢复前书库', exact: true }).click();
  expect((await rpc('book.list', {})).result.books).toHaveLength(2);
  await page.getByRole('button', { name: '切换到恢复书库', exact: true }).click();
  expect((await rpc('book.list', {})).result.books).toHaveLength(1);
});

async function seedChat(count = 1) {
  const chars = [];
  for (let index = 0; index < count; index++) {
    const created = await rpc('roleplay.character_save', {
      persona: {
        name: count === 1 ? '灯塔守望者' : '同名角色',
        introduction: '公开的守望者简介',
        personality: '谨慎温柔',
        private_knowledge: `私有口令-${index}`,
        style: '安慰语气',
      },
    });
    chars.push(created.result.id);
  }
  const conversation = await rpc('roleplay.create', {
    title: '灯塔会话',
    character_ids: chars,
    scene: '雨夜的灯塔',
  });
  return conversation.result;
}
async function seedChatProviders(page: import('@playwright/test').Page) {
  const llm = 'a'.repeat(32),
    tts = 'b'.repeat(32);
  for (const [id, kind, protocol] of [
    [llm, 'llm', 'openai_chat'],
    [tts, 'tts', 'openai_speech'],
  ]) {
    await rpc('provider.save', {
      config: {
        id,
        name: kind === 'llm' ? '聊天替身文本' : '聊天替身语音',
        kind,
        protocol,
        base_url: 'https://fixture.example/v1',
        model: 'fixture-model',
        voice: 'fixture-voice',
        requires_key: false,
        max_output_tokens: 128,
      },
    });
  }
  await rpc('network.set', { enabled: true });
  await page.evaluate(
    ({ llm, tts }) => {
      localStorage.setItem('narravo.llm', llm);
      localStorage.setItem('narravo.tts', tts);
    },
    { llm, tts },
  );
  await page.reload();
}

test('roleplay local: independent characters, user persona, no-model message, reopen and export', async ({
  page,
}) => {
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  for (const [kind, name] of [
    ['character', '纸鸢'],
    ['character', '小舟'],
    ['user', '虚构旅人'],
  ]) {
    await page.getByRole('button', { name: '新建角色 / 用户身份', exact: true }).click();
    await page.getByLabel('角色类型', { exact: true }).selectOption(kind);
    await page.getByLabel('角色名称', { exact: true }).fill(name);
    await page.getByLabel('公开简介', { exact: true }).fill('愿意听故事的虚构对象');
    await page.getByRole('button', { name: '保存人设', exact: true }).click();
  }
  await page.getByRole('button', { name: '新建单聊 / 群聊', exact: true }).click();
  await page.getByLabel('会话名称', { exact: true }).fill('无模型群聊');
  await page.getByLabel(/纸鸢 · /).check();
  await page.getByLabel(/小舟 · /).check();
  await page.getByLabel('用户身份', { exact: true }).selectOption({
    label: (await page.getByLabel('用户身份').locator('option').allTextContents()).find((v) =>
      v.includes('虚构旅人'),
    )!,
  });
  await page.getByRole('button', { name: '创建会话', exact: true }).click();
  await page
    .getByLabel('聊天消息', { exact: true })
    .fill(
      '这是本地保存的问候😀。<script>window.__roleplay_injected = true</script><img src="https://untrusted.invalid/pixel">',
    );
  await page.getByRole('button', { name: '保存本地消息', exact: true }).click();
  await expect(page.locator('.rp-messages')).toContainText('这是本地保存的问候😀。');
  await expect(page.getByRole('status').filter({ hasText: '尚未配置 LLM' })).toBeVisible();
  expect((await rpc('book.list', {})).result.books).toEqual([]);
  await expect(page.locator('.rp-messages script, .rp-messages img')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__roleplay_injected)).toBeUndefined();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: '导出聊天', exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('无模型群聊.txt');
  await page.getByRole('button', { name: '角色库与会话', exact: true }).click();
  await page.getByRole('button', { name: /无模型群聊.*2 位角色/ }).click();
  await expect(page.locator('.rp-messages')).toContainText('虚构旅人');
});

test('roleplay text and sentence speech: real adapter, first sentence, stable voice, stop and variants', async ({
  page,
}) => {
  await seedChat();
  await seedChatProviders(page);
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  await page.getByRole('button', { name: /灯塔会话.*1 位角色/ }).click();
  await page.getByLabel('发送后自动朗读（可能计费）').check();
  await page.getByLabel('聊天消息', { exact: true }).fill('你好，请安慰一下我。');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.locator('.rp-partial')).toContainText('你好😀。');
  await expect
    .poll(
      async () => {
        const lib = await rpc('roleplay.library', {});
        const view = await rpc('roleplay.get', { conversation_id: lib.result.conversations[0].id });
        return (
          view.result.turns[0].speech.some((s: any) => s.asset_id) &&
          view.result.turns[0].status === 'running'
        );
      },
      { intervals: [80] },
    )
    .toBe(true);
  await expect(page.locator('.rp-messages')).toContainText('完整回复 · 已自动保存');
  await page.getByRole('button', { name: '停止语音', exact: true }).click();
  await page.getByRole('button', { name: '上下文预览', exact: true }).click();
  await page.getByRole('button', { name: '预览实际上下文', exact: true }).click();
  await expect(page.locator('.rp-context').first()).toContainText('chat_scoped');
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '生成另一变体', exact: true }).click();
  await expect(page.getByLabel(/回复变体/)).toBeVisible();
  await page.getByLabel(/回复变体/).selectOption({ index: 1 });
  await page.getByRole('button', { name: /编辑消息 灯塔守望者/ }).click();
  await page.getByLabel('编辑消息', { exact: true }).fill('我会守着灯，等天亮。');
  await page.getByRole('button', { name: '保存为新历史路径', exact: true }).click();
  await expect(page.locator('.rp-messages')).toContainText('我会守着灯，等天亮。');
  await page.screenshot({ path: '.build-tools/roleplay.png' });
});

test('roleplay group: explicit IDs, all and situation queues are finite; mute and remove retain history', async ({
  page,
}) => {
  const initial = await seedChat(3);
  await seedChatProviders(page);
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  await page.getByRole('button', { name: /灯塔会话.*3 位角色/ }).click();
  await page.getByLabel('聊天消息', { exact: true }).fill('每位守望者说一句话。');
  await page.getByLabel('发言模式', { exact: true }).selectOption('all');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(
    page.locator('.rp-message').filter({ hasText: '完整回复 · 已自动保存' }),
  ).toHaveCount(3);
  await expect(page.getByText('本轮已完成 · 已提交 3 次请求', { exact: true })).toBeVisible();
  await page.getByLabel('发言模式', { exact: true }).selectOption('situation');
  await page.getByLabel('聊天消息', { exact: true }).fill('谁愿意继续守夜？');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByText('本轮已完成 · 已提交 4 次请求', { exact: true })).toBeVisible();
  const view = (await rpc('roleplay.get', { conversation_id: initial.id })).result;
  expect(view.turns[1].completed_members).toEqual(initial.members.map((m: any) => m.id));
  await page.getByRole('button', { name: '成员、人设与声音', exact: true }).click();
  await page.getByLabel('禁言', { exact: true }).first().check();
  await page.getByLabel('移出（保留历史）', { exact: true }).last().check();
  await page.getByRole('button', { name: '停止旧轮并保存配置', exact: true }).click();
  expect((await rpc('roleplay.get', { conversation_id: initial.id })).result.messages).toHaveLength(
    8,
  );
  await expect(page.locator('.rp-mentions input:disabled')).toHaveCount(1);
  await page.getByRole('button', { name: '历史路径', exact: true }).click();
  await expect(page.locator('.rp-history button')).not.toHaveCount(0);
});

test('roleplay novel copy previews selected visible fields and requires explicit author material', async ({
  page,
}) => {
  const workspace = (await rpc('book.create', { title: '人物复制验收' })).result;
  await rpc('planning.save', {
    branch_id: workspace.branch_id,
    expected_snapshot: workspace.snapshot_id,
    entries: [
      {
        id: 'fixture-person',
        kind: 'character',
        title: '旅人',
        text: '未披露的虚构身份秘密',
        author_only: true,
      },
    ],
  });
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  await page.getByRole('button', { name: '从作品复制人物', exact: true }).click();
  await page.getByRole('combobox', { name: '作品', exact: true }).selectOption(workspace.branch_id);
  await page.getByRole('button', { name: '预览所选资料', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('当前位置不可见');
  await page
    .getByRole('checkbox', { name: '明确选入作者资料（会在聊天生成时发送给模型）', exact: true })
    .check();
  await page.getByRole('button', { name: '预览所选资料', exact: true }).click();
  await expect(page.locator('.rp-context')).toContainText('未披露的虚构身份秘密');
  await expect(page.getByText(/包含作者资料，模型可能披露/)).toBeVisible();
  await page.getByRole('button', { name: '确认复制为独立角色', exact: true }).click();
  const library = (await rpc('roleplay.library', {})).result;
  expect(library.characters).toHaveLength(1);
  expect(library.characters[0].persona.introduction).toBe('');
  expect(library.characters[0].persona.background).toBe('未披露的虚构身份秘密');
  expect(JSON.parse(library.characters[0].source).fields).toEqual(['background']);
  expect((await rpc('book.list', {})).result.books).toHaveLength(1);
});

test('roleplay backup switches libraries with fresh chat state and preserves original messages', async ({
  page,
}) => {
  const { readFile } = await import('node:fs/promises');
  const chat = await seedChat();
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  await page.getByRole('button', { name: /灯塔会话.*1 位角色/ }).click();
  await page.getByLabel('聊天消息', { exact: true }).fill('备份中的本地消息。');
  await page.getByRole('button', { name: '保存本地消息', exact: true }).click();
  await page.getByRole('button', { name: '备份与恢复', exact: true }).click();
  await page.getByRole('button', { name: '创建完整备份', exact: true }).click();
  await expect(page.getByText('备份已准备，可保存文件', { exact: true })).toBeVisible();
  const id = await page.evaluate(() => localStorage.getItem('narravo.file-operation'));
  const backup = await readFile(resolve(directory, 'outbox', `${id}.narravo`));
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  await page.getByRole('button', { name: /灯塔会话.*1 位角色/ }).click();
  await page.getByLabel('聊天消息', { exact: true }).fill('仅原书库保留的第二条。');
  await page.getByRole('button', { name: '保存本地消息', exact: true }).click();
  for (let i = 0; i < 4; i++) await rpc('roleplay.silence', { conversation_id: chat.id });
  await page.getByRole('button', { name: '备份与恢复', exact: true }).click();
  await page
    .getByLabel('测试恢复文件')
    .setInputFiles({ name: 'chat.narravo', mimeType: 'application/zip', buffer: backup });
  await expect(page.getByText('校验通过，等待恢复为独立书库', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '恢复为独立书库并切换', exact: true }).click();
  await expect(
    page.getByText('已切换至恢复书库；原书库仍保留在本机', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '角色扮演', exact: true }).click();
  await page.getByRole('button', { name: /灯塔会话.*1 位角色/ }).click();
  await expect(page.locator('.rp-messages')).toContainText('备份中的本地消息。');
  await expect(page.locator('.rp-messages')).not.toContainText('仅原书库保留的第二条。');
  await page.getByLabel('聊天消息', { exact: true }).fill('恢复后仍可本地保存。');
  await page.getByRole('button', { name: '保存本地消息', exact: true }).click();
  await expect(page.locator('.rp-messages')).toContainText('恢复后仍可本地保存。');
});
