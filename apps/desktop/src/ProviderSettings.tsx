import { useEffect, useState } from 'react';
import { Plus, Save, Settings2 } from 'lucide-react';
import { clearProviderKey, rpc, saveProvider } from './rpc';
import { message } from './store';
import { AudioPlayer } from './AudioPlayer';
import type {
  ProviderConfig,
  ProviderList,
  ProviderTemplate,
  Task,
} from '../../../packages/contracts';

type ProviderKind = ProviderConfig['kind'];
const kinds = ['llm', 'tts'] as const;
const kindNames = { llm: '文本模型（LLM）', tts: '语音模型（TTS）' };
const protocols = {
  llm: ['openai_chat', 'openai_responses', 'anthropic'],
  tts: ['openai_speech', 'minimax_speech', 'elevenlabs'],
};
const fresh = (kind: ProviderKind): ProviderConfig => ({
  id: crypto.randomUUID().replaceAll('-', ''),
  name: '',
  kind,
  protocol: kind === 'llm' ? 'openai_chat' : 'openai_speech',
  base_url: '',
  model: '',
  region: 'custom',
  voice: '',
  context_limit: 16384,
  max_output_tokens: 2048,
  token_parameter: 'max_tokens',
  include_usage: false,
  send_temperature: false,
  temperature: 0.8,
  allow_local: false,
  requires_key: true,
});
const protocolNames = {
  openai_chat: 'Chat Completions（兼容）',
  openai_responses: 'OpenAI Responses',
  anthropic: 'Claude Messages',
  openai_speech: 'OpenAI Speech（兼容）',
  minimax_speech: 'MiniMax 语音',
  elevenlabs: 'ElevenLabs 语音',
};

type SettingsProps = {
  state: ProviderList;
  refresh: () => Promise<void>;
  onSaved: (config: ProviderConfig) => void;
};

export function ProviderSettings({
  state,
  refresh,
  onSaved,
  initialKind = 'llm',
}: SettingsProps & { initialKind?: ProviderKind }) {
  const [kind, setKind] = useState(initialKind);
  const [templates, setTemplates] = useState<ProviderTemplate[]>([]);
  const [networkEnabled, setNetworkEnabled] = useState(state.external_enabled);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setNetworkEnabled(state.external_enabled), [state.external_enabled]);
  useEffect(() => setKind(initialKind), [initialKind]);
  useEffect(() => {
    rpc('provider.catalog', {})
      .then((result) => setTemplates(result.templates))
      .catch((e) => setError(message(e)));
  }, []);
  return (
    <div className="provider-settings">
      <div className="provider-tabs" role="tablist" aria-label="模型配置分类">
        {kinds.map((item, index) => (
          <button
            key={item}
            id={`provider-tab-${item}`}
            role="tab"
            aria-selected={kind === item}
            aria-controls={`provider-panel-${item}`}
            tabIndex={kind === item ? 0 : -1}
            onClick={() => setKind(item)}
            onKeyDown={(event) => {
              let next: ProviderKind;
              if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = kinds[1 - index];
              else if (event.key === 'Home') next = 'llm';
              else if (event.key === 'End') next = 'tts';
              else return;
              event.preventDefault();
              setKind(next);
              document.getElementById(`provider-tab-${next}`)?.focus();
            }}
          >
            {kindNames[item]}
          </button>
        ))}
      </div>
      <label className="network-toggle">
        <input
          type="checkbox"
          checked={networkEnabled}
          disabled={busy}
          onChange={async (event) => {
            const enabled = event.currentTarget.checked;
            setNetworkEnabled(enabled);
            setBusy(true);
            setError('');
            try {
              await rpc('network.set', { enabled });
              await refresh();
            } catch (e) {
              setNetworkEnabled(state.external_enabled);
              setError(message(e));
            } finally {
              setBusy(false);
            }
          }}
        />
        <span>
          允许外部模型请求
          <small>此开关同时控制 LLM 和 TTS。关闭后停止活动请求；已发出的请求可能仍计费。</small>
        </span>
      </label>
      {error && (
        <p className="warning" role="alert">
          {error}
        </p>
      )}
      {kinds.map((item) => (
        <div
          key={item}
          id={`provider-panel-${item}`}
          role="tabpanel"
          aria-labelledby={`provider-tab-${item}`}
          hidden={kind !== item}
          tabIndex={0}
        >
          <ProviderEditor
            kind={item}
            templates={templates.filter((t) => t.kind === item)}
            state={state}
            refresh={refresh}
            onSaved={onSaved}
          />
        </div>
      ))}
    </div>
  );
}

function ProviderEditor({
  kind,
  templates,
  state,
  refresh,
  onSaved,
}: SettingsProps & {
  kind: ProviderKind;
  templates: ProviderTemplate[];
}) {
  const [config, setConfig] = useState<ProviderConfig>(() => fresh(kind));
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [test, setTest] = useState<Task | null>(null);
  const [templateId, setTemplateId] = useState('');
  const providers = state.providers.filter((p) => p.kind === kind);
  const existing = providers.find((p) => p.id === config.id);
  const retained = existing?.has_credential && existing.base_url === config.base_url;
  const label = kind.toUpperCase();
  useEffect(() => {
    if (test?.status !== 'running') return;
    let inFlight = false;
    const timer = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next = await rpc('task.get', { task_id: test.task_id });
        setTest(next);
      } catch (e) {
        setError(message(e));
      } finally {
        inFlight = false;
      }
    }, 250);
    return () => clearInterval(timer);
  }, [test?.task_id, test?.status]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function applyTemplate(id: string) {
    setTemplateId(id);
    const entry = templates.find((t) => t.id === id);
    if (!entry) return;
    setConfig({
      ...fresh(kind),
      kind,
      name: entry.name,
      protocol: entry.protocol,
      base_url: entry.base_url,
      region: entry.region,
      model: entry.model ?? '',
      voice: entry.voice ?? '',
      token_parameter: entry.token_parameter ?? 'max_tokens',
    });
    setApiKey('');
    setTest(null);
    setNotice('');
  }
  async function save() {
    await saveProvider(config, apiKey);
    onSaved(config);
    setApiKey('');
    await refresh();
    setNotice(`${label} 配置已保存。尚未通过真实请求测试。`);
  }
  return (
    <div className="provider-editor">
      <p className="muted small">
        {kind === 'llm' ? '用于创作、开篇与续写。' : '用于将正文合成为语音。'}
        本页独立保存 {label} 的账号、模型{kind === 'tts' ? '、音色' : ''}与密钥。
      </p>
      {error && (
        <p className="warning" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="settings-notice" role="status">
          {notice}
        </p>
      )}
      <h3 className="provider-list-heading">已保存的 {label} 配置</h3>
      {providers.length === 0 && (
        <p className="small muted">暂无 {label} 配置，请选择下方预设添加。</p>
      )}
      <div className="provider-saved-list">
        {providers.map((item) => (
          <button
            key={item.id}
            className={config.id === item.id ? 'selected' : ''}
            disabled={busy}
            onClick={() => {
              const { has_credential: _status, ...saved } = item;
              setConfig(saved);
              setApiKey('');
              setTemplateId('');
              setTest(null);
              setNotice('');
            }}
          >
            <Settings2 size={14} />
            <span>
              {item.name}
              <small>
                {item.kind === 'llm' ? '文本模型' : '语音模型'} · {item.model} ·{' '}
                {item.has_credential ? '密钥已保存' : item.requires_key ? '待填密钥' : '无需密钥'}
              </small>
            </span>
          </button>
        ))}
      </div>
      <fieldset className="provider-fields" disabled={busy}>
        <label className="field-label" htmlFor={`${kind}-provider-template`}>
          添加服务预设
        </label>
        <select
          id={`${kind}-provider-template`}
          className="field-select"
          value={templateId}
          disabled={busy}
          onChange={(e) => applyTemplate(e.target.value)}
        >
          <option value="">选择服务商，或编辑上面的已有配置</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        {templateId && (
          <p className="small muted">{templates.find((t) => t.id === templateId)?.note}</p>
        )}
        <div className="provider-form-grid">
          <div>
            <label className="field-label" htmlFor={`${kind}-provider-name`}>
              配置名称
            </label>
            <input
              id={`${kind}-provider-name`}
              className="field-input"
              value={config.name}
              maxLength={80}
              onChange={(e) => setConfig({ ...config, name: e.target.value })}
            />
          </div>
          <div>
            <label className="field-label" htmlFor={`${kind}-provider-region`}>
              账号 / 区域标记
            </label>
            <input
              id={`${kind}-provider-region`}
              className="field-input"
              value={config.region}
              onChange={(e) => setConfig({ ...config, region: e.target.value })}
            />
          </div>
        </div>
        <label className="field-label" htmlFor={`${kind}-provider-protocol`}>
          接口协议
        </label>
        <select
          id={`${kind}-provider-protocol`}
          className="field-select"
          value={config.protocol}
          onChange={(e) => {
            const protocol = e.target.value as ProviderConfig['protocol'];
            setConfig({
              ...config,
              protocol,
              kind,
            });
          }}
        >
          {Object.entries(protocolNames)
            .filter(([value]) => protocols[kind].includes(value))
            .map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
        </select>
        <label className="field-label" htmlFor={`${kind}-provider-url`}>
          API 基础地址
        </label>
        <input
          id={`${kind}-provider-url`}
          className="field-input"
          value={config.base_url}
          placeholder="https://服务域名/v1"
          onChange={(e) => setConfig({ ...config, base_url: e.target.value.trim() })}
        />
        <p className="small muted">
          填写基础地址，不含 chat/completions 等方法路径；更换地址后需要为新地址重新填写密钥。
        </p>
        <label className="field-label" htmlFor={`${kind}-provider-model`}>
          模型 ID
        </label>
        <input
          id={`${kind}-provider-model`}
          className="field-input"
          value={config.model}
          placeholder="填写 API 控制台中可用的精确模型 ID"
          maxLength={160}
          onChange={(e) => setConfig({ ...config, model: e.target.value.trim() })}
        />
        {config.kind === 'tts' && (
          <>
            <label className="field-label" htmlFor={`${kind}-provider-voice`}>
              音色 ID
            </label>
            <input
              id={`${kind}-provider-voice`}
              className="field-input"
              value={config.voice}
              placeholder="填写该服务支持的音色 ID"
              onChange={(e) => setConfig({ ...config, voice: e.target.value.trim() })}
            />
            <p className="small muted">
              普通旁白模式；不自动换音色。当前不发送情绪指令、SSML 或声音克隆请求。
            </p>
          </>
        )}
        <label className="field-label" htmlFor={`${kind}-provider-key`}>
          API Key {retained ? '（已保存，留空保留）' : ''}
        </label>
        <input
          id={`${kind}-provider-key`}
          className="field-input"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          placeholder={retained ? '不会读取或显示已保存的密钥' : '仅写入系统凭据库，不存正文数据库'}
          onChange={(e) => setApiKey(e.target.value)}
        />
        {retained && (
          <button
            className="text-danger"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await clearProviderKey(config.id);
                await refresh();
                setNotice('已移除此配置的已保存密钥。');
              })
            }
          >
            移除此配置的密钥
          </button>
        )}
        <details className="provider-advanced">
          <summary>高级参数与本地服务</summary>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={config.allow_local}
              onChange={(e) => setConfig({ ...config, allow_local: e.target.checked })}
            />
            明确允许此配置访问本地 / 内网服务和 HTTP
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={config.requires_key}
              onChange={(e) => setConfig({ ...config, requires_key: e.target.checked })}
            />
            此服务需要 API Key
          </label>
          {config.kind === 'tts' && config.protocol === 'minimax_speech' && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={config.speech_expression ?? false}
                onChange={(e) => setConfig({ ...config, speech_expression: e.target.checked })}
              />
              启用已核对的 MiniMax 2.6 语气 /
              速度参数（happy、sad、angry；需按账号核验，其他模型回退普通语气）
            </label>
          )}
          {config.kind === 'llm' && (
            <>
              <div className="provider-form-grid">
                <div>
                  <label className="field-label" htmlFor={`${kind}-context-limit`}>
                    模型上下文上限
                  </label>
                  <input
                    id={`${kind}-context-limit`}
                    className="field-input"
                    type="number"
                    min={2048}
                    max={2000000}
                    value={config.context_limit}
                    onChange={(e) =>
                      setConfig({ ...config, context_limit: Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor={`${kind}-output-limit`}>
                    单次输出 token 上限
                  </label>
                  <input
                    id={`${kind}-output-limit`}
                    className="field-input"
                    type="number"
                    min={16}
                    max={32768}
                    value={config.max_output_tokens}
                    onChange={(e) =>
                      setConfig({ ...config, max_output_tokens: Number(e.target.value) })
                    }
                  />
                </div>
              </div>
              <label className="field-label" htmlFor={`${kind}-token-param`}>
                Chat 接口输出参数
              </label>
              <select
                id={`${kind}-token-param`}
                className="field-select"
                value={config.token_parameter}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    token_parameter: e.target.value as ProviderConfig['token_parameter'],
                  })
                }
              >
                <option value="max_tokens">max_tokens</option>
                <option value="max_completion_tokens">max_completion_tokens</option>
              </select>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={config.include_usage}
                  onChange={(e) => setConfig({ ...config, include_usage: e.target.checked })}
                />
                发送 stream_options.include_usage（须确认兼容）
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={config.send_temperature}
                  onChange={(e) => setConfig({ ...config, send_temperature: e.target.checked })}
                />
                发送温度参数（部分推理模型不支持）
              </label>
              {config.send_temperature && (
                <input
                  aria-label="温度"
                  className="field-input"
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={config.temperature}
                  onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })}
                />
              )}
            </>
          )}
        </details>
        <div className="inline-actions">
          <button
            className="primary-button"
            disabled={busy || !config.name || !config.model || !config.base_url}
            onClick={() => void run(save)}
          >
            <Save size={15} />
            保存 {label} 配置
          </button>
          <button
            className="outline-button"
            disabled={busy}
            onClick={() => {
              setConfig(fresh(kind));
              setApiKey('');
              setTemplateId('');
              setTest(null);
            }}
          >
            <Plus size={15} />
            新建 {label} 配置
          </button>
        </div>
      </fieldset>
      <div className="provider-test">
        <p className="small muted">
          {kind === 'llm' ? '文本测试最多输出 64 tokens。' : '语音测试仅合成一句话。'}
          测试将保存本页配置并发送固定问候语，可能产生费用；不发送你的小说。
        </p>
        <button
          className="outline-button"
          disabled={busy || !existing || !state.external_enabled || test?.status === 'running'}
          onClick={() =>
            void run(async () => {
              await save();
              setTest(await rpc('provider.test', { config_id: config.id }));
              setNotice('正在测试所选模型，请勿重复请求。');
            })
          }
        >
          测试 {label}（可能计费）
        </button>
        {test && (
          <>
            <p className="small" role="status">
              {test.status === 'running' ? '请求中…' : (test.message ?? test.status)}
            </p>
            {test.status === 'running' && (
              <button
                className="outline-button"
                onClick={() =>
                  void run(async () => setTest(await rpc('task.cancel', { task_id: test.task_id })))
                }
              >
                停止测试
              </button>
            )}
            {test.audio && test.audio.segments.length > 0 && (
              <AudioPlayer plan={test.audio} onError={setError} />
            )}
            <p className="small muted">
              已提交 {test.usage?.requests_submitted ?? 0} 次请求 · 费用未知，请以服务平台账单为准。
            </p>
          </>
        )}
      </div>
      <p className="small muted">
        OpenAI、Claude 等网页登录订阅与 API
        密钥分别管理。模型名可手动更新；切换服务不会自动转发密钥或正文。
      </p>
    </div>
  );
}
