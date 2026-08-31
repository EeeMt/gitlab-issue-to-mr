# OpenCode Server 探针证据 (§3.3)

**制品：** OpenCode `1.18.19` linux-x64 · **模式：** Task-scoped Server (`opencode serve --port --hostname`) · **控制协议:** server_http (OpenAPI 3.1, `/doc`) + SSE 事件订阅

**probe 环境：** 远端 `v2probe` 容器。模型协议走 DeepSeek-Anthropic 兼容端点（`opencode.json` 自定义 provider，`npm: @ai-sdk/anthropic`，`baseURL: https://api.deepseek.com/anthropic`，`apiKey: {env:DEEPSEEK_ANTHROPIC_KEY}` —— 注意 OpenCode 的 env 插值语法是 **`{env:VAR}`，不是 `$VAR`**，用错会导致将字面量当 key 且模型调用 401）。key 未进入任何 fixture/日志。

## Probe 矩阵结果

| 场景 | 结果 | 关键证据 |
|---|---|---|
| start / health / auth / 随机端口 | ✅ | `serve --port` 监听；`/` 返回 SPA / `/doc` 返回 OpenAPI 3.1（**162 paths**）；**无 `OPENCODE_SERVER_PASSWORD` 时服务器未受保护**；设密码后 `Basic` 认证：无凭据 `/session` → 401，`Basic opencode:<pw>` → 200。**用户名固定为 `opencode`**（`OPENCODE_SERVER_USERNAME` 可改，默认 `opencode`）；`WWW-Authenticate: Basic realm="Secure Area"` |
| Session（建会话） | ✅ | `POST /session` 需 `model:{id,providerID}`；返回 `ses_…` + `version: 1.18.19` + `directory` |
| 异步 Prompt | ✅ | `POST /session/{id}/prompt_async` 返回 **204**（异步接收，非消息体）；`parts:[{type:text,text}]` |
| 事件订阅 / settled 判定 | ✅ | 全局 `GET /event`（SSE, text/event-stream）实时推送；事件类型：`server.connected`、`server.heartbeat`、`session.created/updated`、`session.status(busy)`、`message.updated`、`message.part.updated`、`message.part.delta`(流式 token)、`session.diff`、**`session.idle`（= settled 信号）**；也见 `GET /session/status` 轮询 `{type:busy}` → `{}` |
| Abort | ✅ | `POST /session/{id}/abort` 返回 **200 + `true`**；随后 assistant 消息 `error:true` 且带 completed 时间戳（操作被中断、settled 为错误态） |
| Server 崩溃 | ⏳ | 未做主动崩溃注入（kill -9 serve 进程即模拟）；作为设备级异常由 Runner 的进程级 TERM/KILL 兜底。**待测** |

## SDK-vs-HTTP 探针判定（§3.3 历史决策项）

本节记录 Phase 0 探针阶段的 SDK 倾向性结论；Phase 3 实现前置 gate 随后因 Worker Bundle 成本将生产路径
冻结为 Python HTTP/SSE Bridge。当前实现与边界以
`docs/architecture/open-harness-v2-phase3-opencode-design.md` §2 为准，本节不作为当前 Runtime Bundle
composition 的生产路径声明。

**探针阶段结论：倾向官方 `@opencode-ai/sdk`（Node SDK），基于其稳定 OpenAPI 3.1；此结论未锁定最终
Worker 实现路径。**

依据：
1. **stable OpenAPI 3.1 规范**：`/doc` 输出 OpenAPI 3.1，162 个 path，含完整的 request/response schema、`TextPartInput`、`OutputFormat`、`SessionStatus`、`Event` 等定义 —— 是唯一的事实协议源。
2. **官方 SDK 由该 spec 生成**：`opencode-ai` npm SDK 直接从 OpenAPI 生成客户端，类型与运行时保持一致，避免 hand-rolled HTTP 代理漂移；Worker 侧（V2 内置 harness，Node runtime）可直接依赖。
3. **事件驱动已证实**：SSE `/event` + `session.idle` 提供与 Pi `agent_settled` 等价的 settled 判定；SDK 对 SSE 流式事件有封装，比裸 HTTP `curl` 订阅更稳。
4. **Command/Abort 语义已证实**：`abort` 返回 typedd `true` 并中断异步 prompt；SDK 方法签名与 spec 对齐。
5. **互通性风险**：SDK 依赖 Node 侧 bundle；若 Worker-kit 希望避免 Node 依赖，可退化为 HTTP 直连 + 自维护 SSE 解析（诊断路径）。**选 SDK 需在成本重估时计入 Node runtime 与 SDK 版本冻结。**

> 关于 §3.3 的 "随机端口"：Server 可显式 `--port` 或默认随机；Bridge 启动后从本地控制端点获取端口，非阻塞项。

## 配置关键点（V2 provider 接线输入）

- 自定义 provider 需 `opencode.json`：`{ "provider": { "<id>": { "npm": "@ai-sdk/anthropic", "options": { "baseURL": "…", "apiKey": "{env:VAR}" }, "models": { "<model>": {…} } } } }`。
- **`{env:VAR}` 插值是必须的**；`$VAR` 不会插值。
- Anthropic 兼容端点需配 `@ai-sdk/anthropic` 包；OpenAI-compatible 配 `@ai-sdk/openai-compatible`（V2 `compat_profile` 在 Endpoint 声明，不从 provider 层新增协议名）。

## 事件类型清单 (Observed, SSE)

`server.connected` · `server.heartbeat` · `session.created` · `session.updated` · `session.status(busy)` · `session.idle` · `session.diff` · `message.updated` · `message.part.updated` · `message.part.delta`。未复现（列待测）：`session.error`、compaction/自动重试事件、`permission`/`question` 阻塞（需工具调用场景）。
