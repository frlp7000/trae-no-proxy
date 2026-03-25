# Trae Custom Endpoint Protocol Matrix

这份文档只回答一个工程问题：

`Trae 当前实际会发哪类协议，newapi / OpenRouter / LiteLLM 这类网关又各自兼容到哪一层？`

## 先说结论

- 目前对 Trae 的本地逆向证据，强烈指向它至少内置了三套 provider 适配：
  - OpenAI Chat Completions 风格
  - Anthropic Messages 风格
  - Gemini provider 分支
- 但 `provider 名称` 和 `最终发出的线协议` 不是一回事。
  - 已抓到一次运行时日志：`provider: "gemini"`，实际请求 URL 却是 `/v1/chat/completions`
- 当前没有足够证据证明 Trae 自定义模型路径已经在用 `OpenAI Responses` 作为主协议。
- 所以补丁项目下一步不应该继续围绕“替换域名”设计，而应该围绕：
  - `provider`
  - `protocol profile`
  - `local adapter / relay`

## Trae 本地证据

已经确认到的本地证据：

- `ai_agent.dll` 中可以看到这些 provider 相关路径：
  - `provider/openai.rs`
  - `provider/anthropic.rs`
  - `provider/gemini.rs`
- 同一个二进制里能看到这些协议痕迹：
  - `/v1/chat/completions`
  - `/messages`
  - `cache_control`
  - `cache_creation_input_tokens`
  - `cache_read_input_tokens`
- 2026-03-25 抓到的运行时日志里，自定义模型请求出现：
  - `provider: "gemini"`
  - `request url: "https://.../v1/chat/completions"`

这说明两件事：

1. Trae 不是单纯把所有模型都走一个统一 SDK 黑盒。
2. UI 里看到的“供应商”标签，不足以推出最终 HTTP 协议形状。

## 官方协议矩阵

| 协议 | 典型路径 | 输入主结构 | 流式形状 | 工具调用主结构 | 缓存语义 | 与 Trae 当前证据的贴合度 |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI Chat Completions | `/v1/chat/completions` | `messages[]` | `chat.completion.chunk`，增量在 `choices[].delta` | `tools[]` + `tool_calls` | 仅 token 级缓存统计常见，协议层缓存语义较弱 | 很强 |
| OpenAI Responses | `/v1/responses` | `input`，可为字符串或 item 数组 | 明确的 SSE event 名称，如 `response.output_text.delta` | `tools[]`，输出里是 `output[].type=function_call` | 支持 `previous_response_id`、prompt cache retention 等 | 目前证据不足 |
| Anthropic Messages | `/v1/messages` | `messages[]`，`content[]` 为 block 数组 | SSE 事件流，语义围绕 message/content block | `tools[]` + `tool_use` / `tool_result` block | `cache_control`、`cache_creation_input_tokens`、`cache_read_input_tokens` | 很强 |
| Gemini GenerateContent | `/v1beta/models/{model}:generateContent` | `contents[]`，每条含 `parts[]` | `:streamGenerateContent` | `tools[]` 内 `functionDeclarations`，返回 `functionCalls` | `cachedContent` | 有 provider 证据，但未看到自定义模型路径直接这样发 |

## GitHub SDK 对照

官方 SDK 的调用面和上面的协议是对得上的：

- `openai/openai-node`
  - Chat: `client.chat.completions.create(...)`
  - Responses: `client.responses.create(...)`
- `anthropics/anthropic-sdk-typescript`
  - Messages: `client.messages.create(...)`
  - 流式同样围绕 SSE / message events
- `googleapis/js-genai`
  - Gemini: `ai.models.generateContent(...)`
  - 流式：`ai.models.generateContentStream(...)`

工程含义很直接：

- OpenAI 家族现在至少有两条并行主线：`chat` 和 `responses`
- Anthropic 不是“换个字段名的 chat”，而是 block-based messages 协议
- Gemini 也不是“换个 base_url 的 chat”，而是 `contents/parts` 模型

## 网关类型矩阵

### 1. NewAPI 这类多协议网关

从官方文档看，NewAPI 明确暴露多套入口：

- OpenAI Chat: `/v1/chat/completions`
- OpenAI Responses: `/v1/responses`
- Anthropic Messages: `/v1/messages`
- Gemini Native: `/v1beta/models/{model}:generateContent`

这类网关的优点：

- 可以按客户端真实协议去接，不必强行全部降成 OpenAI Chat
- 更适合做 `protocol profile`

这类网关的风险：

- 不同协议能力往往不是完全等价
- 某些 Gemini 路径可能只支持部分媒体上传形式
- 某些 OpenAI-compatible 路由虽然“能回 200”，但工具历史、reasoning、缓存字段、流式事件不一定完全保真

### 2. OpenRouter 这类“强归一化”网关

OpenRouter 官方文档明确说它主要做 OpenAI Chat 风格归一化：

- 主接口是 `/api/v1/chat/completions`
- 会把不同上游尽量归一成 OpenAI Chat 响应
- 也提供 Responses API beta，但文档明确写了 `stateless only`

这类网关适合：

- 你确定客户端只需要 OpenAI Chat / Responses 兼容面

这类网关不适合直接承诺：

- Anthropic 原生 block 级 tool/result/caching 语义完全保真
- Gemini 原生 `contents/parts` 语义完全保真

### 3. LiteLLM 这类“适配器 / 翻译器”网关

LiteLLM 官方文档强调的是：

- 用统一的 OpenAI 输入输出格式去调用大量上游
- proxy 支持 `/chat/completions` 和 `/responses`
- 内部把请求翻译到 Anthropic、Vertex/Gemini、OpenRouter 等不同 provider

这类网关适合：

- 你希望客户端统一说 OpenAI 格式，由网关做翻译

这类网关的边界：

- 它的核心价值是“统一格式”，不是“完整保留每家原生协议细节”
- 对于 provider-native 特性，常见做法是映射、折叠、退化，不一定逐字段等价

## 对补丁项目的直接结论

如果目标是“尽量兼容 Trae，而不是只兼容一个特定 newapi 站点”，建议协议 profile 至少拆成这三类：

1. `openai-chat`
   - 面向 `/v1/chat/completions`
   - 优先兼容多数 OpenAI-compatible 网关
2. `anthropic-messages`
   - 面向 `/v1/messages`
   - 保留 `cache_control`、`tool_use`、`tool_result`
3. `gemini-native`
   - 面向 `:generateContent` / `:streamGenerateContent`
   - 保留 `contents/parts/tools/cachedContent`

`responses` 建议作为第四类可选 profile，而不是当前主线。理由很简单：

- 官方协议当然重要
- 但你现在补的是 Trae，不是抽象 API 论文
- 当前对 Trae 的本地证据，还不足以证明自定义模型路径已经在稳定使用 `/v1/responses`

## 为什么你之前会遇到“模型明明正常，Trae 却报 400/502”

最常见不是“模型坏了”，而是这几类不兼容：

- `role=tool` 历史消息结构和上游预期不一致
- Anthropic / Gemini 原生 block 或 parts 被错误压扁成 chat 文本
- 网关只兼容“基础 chat”，但不兼容 reasoning / tools / cache / multimodal 组合
- 流式响应虽然返回了 SSE，但事件名或 chunk 形状不是客户端期待的那一套

这也是为什么“curl 一个最小请求成功”并不能说明 `Trae + 真实多轮 + 工具调用` 就一定成功。

## 下一步建议

最稳妥的落地顺序：

1. 在补丁项目里引入 `protocol profile` 概念
2. 先把 relay 从“只修 tool content 数组”升级成“按 profile 适配请求/响应”
3. 第一优先级先做：
   - `openai-chat`
   - `anthropic-messages`
4. `gemini-native` 单独做，不要硬塞进 chat 兼容层
5. `responses` 等拿到 Trae 真实运行证据后再提升优先级

## 参考资料

- OpenAI Chat API
  - https://developers.openai.com/api/reference/resources/chat
- OpenAI Responses API
  - https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI Node SDK
  - https://github.com/openai/openai-node
- Anthropic Messages API
  - https://docs.anthropic.com/en/api/messages
- Anthropic Prompt Caching
  - https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Anthropic TypeScript SDK
  - https://github.com/anthropics/anthropic-sdk-typescript
- Gemini GenerateContent API
  - https://ai.google.dev/api/generate-content
- Google Gen AI SDK
  - https://github.com/googleapis/js-genai
- NewAPI API Overview
  - https://docs.newapi.ai/en/api/
- NewAPI OpenAI Chat
  - https://docs.newapi.ai/en/api/openai-chat/
- NewAPI OpenAI Responses
  - https://docs.newapi.ai/en/api/openai-responses/
- NewAPI Anthropic Messages
  - https://docs.newapi.ai/en/api/anthropic-chat/
- NewAPI Gemini Chat
  - https://docs.newapi.ai/ja/api/google-gemini-chat/
- OpenRouter API Overview
  - https://openrouter.ai/docs/api/reference/overview
- OpenRouter Responses API Beta
  - https://openrouter.ai/docs/api/reference/responses/overview
- LiteLLM Docs
  - https://docs.litellm.ai/
