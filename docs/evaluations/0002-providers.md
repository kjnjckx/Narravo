# 多模型与基础语音接入验收

> 后续更新：EPUB/PDF 与完整备份恢复已在 2026-10-17 落地，见 [验收记录 0003](0003-import-backup.md)。本文保留当轮结果与限制。

## DeepSeek 真实短样本排查（2026-10-18）

用户明确授权测试已配置的 DeepSeek API。仅查询官方 `/models` 并使用固定问候语、64 token 输出上限做两次短请求；没有发送小说、角色资料或历史提示词。密钥从系统凭据库读取，仅在测试进程内使用，没有打印、写入文件或进入提交。

- 官方模型列表请求 HTTP 200，返回 `deepseek-flash`、`deepseek-v4-pro`。
- 当前填写的 `Deepseek-flash` 在 `openai_chat`、`https://api.deepseek.com`、`max_tokens`、无可选温度或用量参数的请求中返回 HTTP 400。服务端明确指出模型名称不匹配。
- 保持同一密钥、地址、协议与请求参数，仅将模型 ID 改为全小写 `deepseek-flash`，请求 HTTP 200，流式正文正常结束。
- 定位为模型 ID 大小写错误。本次验证表明该密钥与网络可完成这一短请求，未验证小说写作质量、长上下文、其他模型、TTS 或完整费用账本。
- 此次只读检查现有配置，没有改写用户书库或保存新的模型配置；用户在模型设置中更正 ID 后保存即可。测试没有自动重试未知结果或切换服务商。

- 日期：2026-10-16
- 环境：macOS arm64 / Python 3.12.13 / Rust 1.99.1；版本以锁文件为准
- 数据：隔离临时书库、自创短句、HTTP 替身；未读取真实账号密钥、未上传真实小说、未发付费调用
- 需求：用户确认接入多种 LLM 和 TTS。此轮交付可配置入口、真实协议适配与基础播放，不宣称每家账号所有模型均已实测

## 配置范围

| 服务 | 协议 / 地址说明 | 验证状态 |
| --- | --- | --- |
| DeepSeek | Chat Completions；api.deepseek.com | 协议替身通过，账号未测 |
| OpenAI / GPT | Chat Completions 或 Responses；api.openai.com/v1 | 两协议替身通过，账号未测 |
| GLM / 智谱 | Chat Completions；open.bigmodel.cn/api/paas/v4 | 兼容适配层通过；官方文档页面读取受限，地址需按控制台再核对，账号未测 |
| Claude | Messages；api.anthropic.com/v1 | 独立鉴权/事件替身通过，账号未测 |
| Gemini | OpenAI 兼容文本接口 | 兼容适配层通过，账号未测 |
| 通义千问 / 百炼 | 北京兼容域名预设，可按控制台替换业务空间地址 | 兼容适配层通过，账号/区域未测 |
| Kimi / Moonshot | 国际端点预设；其他区域按控制台填写 | 兼容适配层通过，账号未测 |
| 硅基流动 | Chat Completions | 兼容适配层通过，账号未测 |
| OpenRouter | Chat Completions；界面说明聚合服务的下游路由行为 | 兼容适配层通过，账号未测 |
| Ollama | 本机兼容接口；须明确允许本地访问与关闭密钥要求 | 兼容适配层通过，未运行本地权重 |
| MiniMax 语音 | 中国/国际分别预设；HTTP hex 音频，不取远端 URL | 独立请求/hex/WAV 替身通过，账号/听感未测 |
| OpenAI / GPT 语音 | Speech，WAV 输出 | 二进制音频/缓存/播放替身通过，账号/听感未测 |
| ElevenLabs | 绑定显式音色 ID，二进制音频 | 请求/鉴权/格式替身通过，账号/听感未测 |
| 自定义 LLM / TTS | 手动协议、基础地址、模型和音色 | 仅保证已实现协议的文本/普通语音子集 |

预设不是实时模型列表，不承诺账号可用性。温度、Chat 输出参数名及可选 usage 请求开关可按模型调整；默认不发送未明确支持的可选参数。未使用未经账号核验的 LLM 模型 ID 作自动默认。

## 已执行检查

- 引擎 pytest：40 项通过；包含原有 19 项，以及三文本/三语音协议、响应脱敏、无重试/无重定向、真实路径的上下文/用量/候选隔离、取消、未知完成、网络关闭、缓存复用、并发缓存合并和迁移回滚。
- 前端 Vitest：2 项通过；Unicode 与合同边界。
- Playwright：5 条通过；原有 4 条写作流程及新增“模型设置 → 固定短样本测试 → 根据正文生成 → 接纳 → 语音准备 → 加载播放 → 再次准备命中缓存 → 编辑后停用旧音频”。使用真实 Python 协议/领域代码和测试专用 HTTP transport，无付费请求，端口 1421 不占用开发应用端口。
- pnpm lint：Prettier、TypeScript、合同生成物一致性通过。
- Ruff / mypy strict 通过。
- cargo fmt / clippy -D warnings / cargo test 通过；普通 Rust 测试 1 项通过，原生凭据库 roundtrip 单独标 ignored。
- 单独执行原生凭据库 roundtrip：使用独立假密钥，写入、读取比较和移除通过，未读取或改动已有凭据。
- macOS .app 构建通过；内置 HTTP/TTS 依赖、迁移与静态校验资源。原生 UI/播放额外检查见本文件末尾记录。

## 失败与边界测试

- 401/403、额度不足、限流、参数错误和 307 重定向均转换为中文动作提示，不输出原始响应，不自动重发。
- 中途流断开保留部分候选，标 UNKNOWN_OUTCOME；取消后不继续提交新的语音片段；进程重启后不自动重新执行远端请求。
- 配置 ID 与服务地址绑定；地址不匹配时拒绝发送当前密钥；配置与任务表中不存在测试密钥。
- 音频必须验证完整文件后才可播放。损坏/JSON 冒充音频被拒绝；源文本的分段覆盖和 emoji code point 范围有针对性测试。
- 已保存同章再次合成使用缓存，第二次 provider 请求数为 0；两个相同合成任务并发仅发一个请求，资产缓存键有唯一索引。
- 本地/内网/HTTP 服务需要显式配置；不继承环境代理，不跟随重定向，不下载 provider 任意返回 URL。
- 升级 0001 → 最新 schema 保留旧书；升级前 backup 包含旧版本；注入 DDL 失败后版本和表结构保持原样。

## 已知限制

实际提供商凭据未配置，因此认证可用性、账号区域、当前模型/音色、真实费用、自然度与原生真实语音听感均未验证。合成格式受到服务账号与模型限制时会报错，不会静默切换声音或服务。ElevenLabs 的真实 MP3 质量/账号响应仍待实测，自动化音频样本为短合成测试 WAV，不代表真实语音质量。

语音为普通旁白，不含 LLM 情绪/角色分析、SSML、声音克隆、逐字时间戳。默认语音串行、完整片段后播放；尚未作长时连续播放与音频间隙指标测量。播放过程中可见的文本是整段，未声称准确逐字同步。

目前费用显示未知，只有输出 token、上下文长度、合成字符数与活动任务数限制，没有金额预算账本和事务预留。短样本测试最多输出 64 tokens，推理模型可能耗尽预算而没有可见正文，需换用合适模型或调整正式生成上限。

音频通过有界 IPC base64 读到前端 Blob，单段上限 8 MiB；大规模库的资产协议和缓存清理后续完善。本地数据未加密，系统 Keychain 只保护凭据。没有正式发行签名/公证和干净机器验证。

## 官方资料核验（2026-10-16）

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events)、[Speech](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)。Responses 完整创建页抓取受限，事件文档与基础 create 请求子集有替身测试；账号未测。
- [DeepSeek 首次调用](https://api-docs.deepseek.com/)、[流式 Chat 合同](https://api-docs.deepseek.com/api/create-chat-completion/)。
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)、[流式事件](https://platform.claude.com/docs/en/build-with-claude/streaming)。
- [GLM 文档](https://docs.bigmodel.cn/)页面读取受限；不宣称已在线验证 GLM 模型 ID 或账号能力，保留手动地址。
- [Gemini 兼容接口](https://ai.google.dev/gemini-api/docs/openai)、[百炼兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。
- [Kimi 国际快速开始](https://platform.kimi.ai/docs/overview)、[硅基流动 Chat](https://docs.siliconflow.cn/docs/api/chat-completions-post)、[OpenRouter API](https://openrouter.ai/docs/api_reference/overview)、[Ollama 兼容接口](https://docs.ollama.com/api/openai-compatibility)。
- [MiniMax 中国语音](https://platform.minimax.cn/docs/api-reference/speech-t2a-http)、[MiniMax 国际语音](https://platform.minimax.io/docs/api-reference/speech-t2a-http)、[ElevenLabs Speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)。
- [keyring 3.6.3 原生凭据存储](https://docs.rs/keyring/3.6.3/keyring/)。

## 原生补充记录

独立复制并重签验收副本，使用单独的应用标识及 `.build-tools/` 隔离书库，没有操作正在运行的开发应用。原生界面已核对完整服务列表；选择 DeepSeek 预设、填写测试模型 ID，保存独立假密钥后界面显示「密钥已保存」且输入清空，随后移除该测试凭据，界面恢复「待填密钥」。全程外部请求关闭，未点击付费测试或生成。

通过任务中心打开预先构造的本地测试 WAV（格式/播放器测试样本，非真实模型音频），真实 WKWebView 加载 Blob 后，点击播放，控件切换为「暂停语音」；停止后正常退出。该结果只证明本地音频解码/播放入口可用，不代表任何服务的实际合成质量、长时连续播放或逐字对齐。

退出后验收副本相关进程为 0，SQLite integrity_check 为 ok，版本为 0003，测试密钥未进入配置数据库。原生工具的首次连接曾异常缓慢，验证结论仅依据其最终返回的可见状态与退出后的只读核对。

## 配置界面分离补充（2026-10-17）

- 对应 PRD 第 10 节 PRO 独立配置和 AC-19 配置入口：设置中分为「文本模型（LLM）」和「语音模型（TTS）」两个可键盘切换的页签。服务预设、协议、已保存列表、编辑草稿、密钥输入、保存与短样本测试分别管理；写作与朗读区直接进入对应页签。
- 复用已有带 kind 的配置记录，不改变数据库、凭据引用或历史配置 ID。保存 LLM 不写 TTS，反之亦然；外部请求总开关仍共用，并明确标注作用范围。
- 新增界面回归验证：跨页签保留未保存草稿和临时密钥输入、服务及协议分类、单独保存、修改 LLM 后 TTS 记录完全一致、刷新恢复、两个直接入口及方向键切换。密钥输入仅为假测试值，保存前清空；无真实凭据或付费请求。
- 本轮检查：Playwright 8 条通过（含原有写作、导入、备份和协议替身生成/播放）；Vitest 2 项通过；格式、TypeScript 和合同一致性通过；前端生产构建和内置 sidecar 的 macOS .app 构建通过。本轮未改引擎或原生凭据逻辑，未重复真实服务或原生 Keychain 验收。
