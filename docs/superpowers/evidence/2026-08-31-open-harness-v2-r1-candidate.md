# Open-Harness V2 R1 Candidate Evidence

本文件是一个候选快照，不是逐次操作日志，也不代表 R1–R5 或 L6 已通过。

## Scope

- 目标 Host：`192.168.50.129`
- 目标平台：`linux/amd64`
- 执行模式：`dual_canary`
- 验证范围：候选服务、Profile 4、Worker Kit、V2 Runtime Bundle、OpenCode HTTP audit/failure 源码及真实 Task 170

## Provider composition

目标 Host 当前的 OpenRouter 配置已为两个 free model 各建立三协议映射；本表只记录非敏感配置，
不包含 credential 或 API key：

| Model | `anthropic_messages` | `openai_responses` | `openai_chat_completions` | Endpoint |
| --- | --- | --- | --- | --- |
| `z-ai/glm-5.2:free` | `openrouter-glm52-anthropic` | `openrouter-glm52-responses` | `openrouter-glm52-chat` | `https://openrouter.ai/api/v1` |
| `minimax/minimax-m3:free` | `openrouter-minimax-anthropic` | `openrouter-minimax-responses` | `openrouter-free` | `https://openrouter.ai/api/v1` |

该表证明 Provider/协议 composition 存在，不等同于三协议真实模型 conformance；后者仍须按 R2 的真实
Host/Task 证据逐项完成。

## Source and service identity

- Open-Harness V2 实现 commit：`ab869c67c22bbcea33cefc4dbc034060e73a4a1f`
- 该 revision 的源码增量已提交；工作树仅保留测试生成的 `.vite` 结果，尚不能作为最终 release revision
  的唯一 composition evidence
- backend/scheduler image：`codify-backend:latest`
- backend/scheduler image ID：`sha256:7b060896d62dab5277acb8408ab5fdc9ebc51f478b546d07d148cdf970e9390d`
- backend：healthy；scheduler：running；数据库容器：healthy

本轮受控源文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `deploy/worker-entrypoint/harness/adapters/opencode_bridge.py` | `c29b8ea3635e14649e10254b91be60552894451e303b77eca70a9a582843108d` |
| `deploy/worker-entrypoint/harness/adapters/opencode_events.py` | `f65f35fe21449b05d0c3022104c33322852285369beb6055915427847de7f4ab` |
| `deploy/worker-entrypoint/harness/adapters/opencode.sh` | `a80b77f4bface050381de54f51a20b4b08faf727b17ff34988835d8f8cb1fb47` |
| `deploy/worker-entrypoint/artifacts.py` | `f86678f50c54c9c73dca3308492ebc4335f6541644f65172a8e0863e1d8d5609` |
| `deploy/worker-entrypoint/bootstrap.sh` | `fd8206e7c2a5dd16bd0bf7e0c04a99ba169ef2e794701a999e2b42975b1fc3a0` |
| `deploy/worker-entrypoint/harness/runner.sh` | `0d5780fdb9532c7b980d238f3cbb5f6579fdbebf293238267c0ec0e449d4d6a5` |

## Profile and Bundle identity

- Profile：`4 / v2-canary-0.6.11-four-harness`
- Worker image：repository-digest pinned `linux/amd64` image
- Worker Kit：`0.6.11`
- Profile image identity generation：`42`
- Worker Kit identity generation：`42`
- Latest readiness: `ready`；Task 170 创建前已重新执行 Profile 4 verify-runtime 并完成 readiness 对账。该状态是短 TTL，后续 canary 仍须在提交前重新 verify。

The four persisted V2 Bundles are:

| Harness | Bundle ID | Bundle digest | Archive SHA-256 |
| --- | ---: | --- | --- |
| Pi | 114 | `6190c48c68dc9127fa73cc653d138f04a6be8fc9fb8c0a39e8c8fa17b02fc1c8` | `35175f46b8daf9b977364502f0a79f41e54e116ac6e562957c48b3b3394e6aaa` |
| OpenCode | 115 | `7769939bf1a0d033a435ea7bd125018acfd55eb04dd3c7ccfce859a30d1747bc` | `640b4716d4dbcf137d4dcd0f76052cd744f9c65a5545cc4a24572b170993b5a2` |
| Claude | 116 | `0b85bbf5f52156c787d347f1c910465644fa1d44fc066c7c8079528e80ace782` | `63c9c403ee314b55f6b73c8c11a007634de94d8c32ef07cd26eb643c3b6f6ddc` |
| Codex | 117 | `00cd008e0f8fd017e692886af66699b7a32176bd50d932a384ec33e9e01cd0dc` | `96e183f74e4498c8d889dcebbcf065d226b1b2d086ca6c0570891c8edbca6946` |

Bundle 115 在其生成时的归档源字节已与当时的本地受控文件逐项一致，且归档实际 SHA-256 与 manifest 中的
`archive_sha256` 一致。`opencode-http-audit.jsonl` 是 Task 运行时 artifact，不会在空的 Bundle 中预置；
真实 OpenCode Task 170 已核对该文件中的逐请求 route/status/config hash；Task 170 使用的最新冻结 Bundle
为下方记录的 Bundle 118（generation 40），不以旧 Bundle 115 的标识替代本次执行证据。

## R2 Pi Provider failure probe

Task `169` 使用 Profile 4、Pi、Bundle `114`、`openrouter-glm52-anthropic`、模型
`z-ai/glm-5.2:free` 和 `anthropic_messages` 完成真实 Host/Provider failure probe：

- 上游返回 HTTP `429`，分类为 `rate_limited` / `upstream_429`，Pi 按策略重试 3 次后失败；
- DB 结果、Task Result 和 Raw Logs 均显示 bounded/sanitized 的 Provider 详情，未退化为孤立 `APIError`；
- canonical stream 共 13 条，只有一个 `harness.failed` 和一个 `run.failed` terminal；attempt 为 closed；
- token usage 为 0，代码变更为 `+0/-0`；runtime archive 为 4,406 bytes，SHA-256 为
  `e17d57ee0e1f84053e53060f99dfb300b44a2b7060c6e5d2fa332b72b61a9690`；
- Task worker 容器已清理。该失败样本证明 failure taxonomy 和展示/归档路径，不计为 Provider 成功或协议 conformance 成功。

## OpenCode nested APIError and HTTP control failure follow-up

- OpenCode 真实 `session.error` 的 `error.data.statusCode/message` 结构已纳入归一化；本地 OpenCode、failure-detail
  聚焦回归为 `80 passed`，完整 backend unit 为 `3233 passed / 4 skipped`。
- OpenCode Bridge 对建 Session、prompt 和 command 的 HTTP 非 2xx 已生成 bounded/sanitized 的 `session.error`，
  不把完整 response envelope 转入 raw/canonical event；本地两条 429/401 失败分类测试已覆盖 `rate_limited` 和
  `authentication_error`，translator 进程也在 setup/early-return 路径统一 close/reap。
- 目标 Host backend/scheduler 已运行包含该修复的镜像 `sha256:7b060896d62dab5277acb8408ab5fdc9ebc51f478b546d07d148cdf970e9390d`；
  Profile 4 随后重新完成四 Harness verify-runtime，页面显示 readiness `Ready`，Profile identity generation 为 `42`。
  这次验证未创建真实 Task，已有 Task 170 的 Bundle `118` 不被追改。
- Task 137 的历史 UI 复核已能展示 bounded/sanitized Provider 详情和 Raw Logs 归档错误；下一条真实 OpenCode Provider
  failure 仍须在新 Bundle 上通过开发环境真实创建 Task 验证 canonical `rate_limited`/`authentication_error` taxonomy；
  本轮未提交该新的真实 Task。

## Failure detail UI verification

- 历史 Task 137（Bundle `103`）的 Task Result 已展示完整的上游 `429` 详情；展开 `Raw Logs` 后可见归档
  错误。其旧 console 仍保留历史的成功提示，因此不能用来证明当前 runner 的终态一致性。
- 当前 candidate Task 169（Bundle `114`）的 Task Result 显示 `rate_limited` 及 bounded/sanitized 429 详情；
  展开 `Raw Logs` 后可见 Harness 非零退出和归档错误，未出现旧 runner 的成功提示。两者均未在展示文本中暴露
  credential。

## R4 responsive UI spot-check

- 针对目标 Host 开发环境的 Task 170 页面完成 390×844、768px 和 1440×900 复核：各视口 `scrollWidth` 与
  `clientWidth` 相等，无横向溢出；Task Result、Raw Logs、Provider、Harness、Worker、长 prompt 和 Completed 状态均可见。
- 根据 390×844 和 768px 实测补齐移动/平板断点的关键操作触控尺寸：实测的 24 个可见按钮/页签（含顶栏、任务操作、prompt
  切换/复制/展开、结果摘要、Provider/Worker 摘要入口、Events/Raw Logs 页签、tool detail 和 continuation
  操作）均达到至少 44px；仅调整 CSS，不改变交互逻辑或桌面断点。
- 该结果仍是 R4 的响应式 spot-check，不代表键盘/安全区、断线重连、command history 或完整 L5 交互验收已通过；
  1440×900 保留桌面原有控件尺寸。

## Verification boundary

- 最近一次完整 backend unit：`3233 passed / 4 skipped`；OpenCode/failure-detail 聚焦 suite：`80 passed`。
- command/session 聚焦回归：`75 passed`，覆盖 command 幂等与 HTTP 路由、pump 严格顺序、closing/closed、
  `outcome_unknown` recovery，以及 Harness session 基础路径。
- frontend unit/build、Ruff、Shell syntax 和 `git diff --check` 已通过。
- 从 Bundle 115 加载实际归档源字节执行回环 HTTP smoke：6 条 audit 记录覆盖 session create/get/prompt/status/abort
  和 SSE event subscribe，含合成 HTTP 429；记录不含请求体、模型名、session ID 或凭据，并包含 task-local config hash。
- 远端 Docker 磁盘未满，本轮未执行镜像清理；若后续确实满盘，只清理已确认的 Codify 调试镜像，不做 broad prune。
- Task 169 的真实 Pi Provider failure probe 和 Task 170 的真实 OpenCode HTTP-audit/namespace 样本已记录在
  上方；下一次真实 Task 提交前仍须重新确认，并重新验证 readiness。

## R2 OpenCode HTTP audit canary

Task `170` 是在目标 Host 的开发环境中通过真实创建任务流程提交的 OpenCode canary；提交前已重新验证
Profile 4 readiness，并显式选择 `openrouter-free`、OpenCode、Freeform、P2、Execute Now 和 Fresh session：

- Task 状态为 `completed`，无错误、无 commit，代码变更为 `+0/-0`；AI Delivery Summary 和 Raw Logs 均展示
  `protocol=openai_chat_completions model=minimax/minimax-m3:free`；页面未出现旧 runner 的
  `Task completed successfully!` 矛盾提示；
- Task 冻结了 Profile `4`、Worker Kit `0.6.11`、V2 Runtime Bundle `118`，Bundle digest 为
  `2ac706bb8f97e3ecc666c40981f26d7d9d976afd485904d0cdca2a5aa341e27b`，Profile generation 为 `40`，
  Worker image 为固定 repository-digest 的 `linux/amd64` image：
  `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`；
- Provider 为 `openrouter-free` / `minimax/minimax-m3:free`，协议为 `openai_chat_completions`，endpoint 为
  `https://openrouter.ai/api/v1`；task snapshot 的 `projected_harness_key` 为 `opencode`，
  `projected_session_namespace` 为 `opencode-e2b9ebf6c92f09f9`；
- Issue 18 的 lineage row 已为 OpenCode generation `26`，`reset_task_id=170`、`last_output_task_id=170`，
  且 namespace 与该 Task snapshot 一致；同 endpoint/config 下复用声明的 namespace 是预期设计，不能把这
  一条 lineage 当成跨 endpoint/config 隔离证明；
- attempt 为 `task-170-attempt-1-ab33960f48dc`，event schema 为 `codify.worker.event/v2`，Adapter 为
  `2.0.0`、OpenCode CLI 为 `1.18.19`；canonical receipt 共 20 条，唯一终态为 `run.completed`，
  `last_seq=20`，attempt 为 `closed`；TaskLog 同时落有 `assistant_text`、`harness_result`、`run_result`
  和 `worker_finalization` 等记录。

运行时 archive 为 `task-170-runtime-archive.tar.gz`，大小 `6,701` bytes，SHA-256 为
`89e042f4f1900eb6ea505192a67323c94313dbf3257066d7e272819abd25cead`。归档成员包括 canonical
`event.jsonl`、`harness-events/opencode.jsonl`、`harness-result.json` 和 `opencode-http-audit.jsonl`。
其中 `harness-result.json` 报告 `server_http` / `opencode-server`、`success=true`、usage 为
`input=7593`、`output=20`。

`opencode-http-audit.jsonl` 的真实记录为：

| Method | Operation | Path template | Status | Outcome |
| --- | --- | --- | ---: | --- |
| `POST` | `session.create` | `/session` | 200 | `success` |
| `POST` | `session.prompt_async` | `/session/{session_id}/prompt_async` | 204 | `success` |
| `GET` | `event.subscribe` | `/event` | 200 | `closed` |

三条记录均为 `codify.opencode.http-audit/v1`，均绑定同一 task-local config path
`/tmp/codify-runtime/opencode/opencode.json`、config SHA-256
`6591a62d9a8e92fbc57c9a0a5fb51611f1d6eedba00b9ce18f945804c9100de5` 和同一 endpoint fingerprint
`v2:851c2f91275f1420238eb5455715d35e`。结构化检查确认 audit 记录不含 request/response body、authorization、
API key、request/response headers 或实际 session ID；`{session_id}` 只出现在脱敏后的 route template 中。
目标 Host 上 Task 170 的 worker 容器已清理。

这补齐了一个真实 OpenCode server HTTP audit 与单 Task namespace 样本，证明了本次冻结 Snapshot 到实际
HTTP 请求的可追溯链路；它仍不等同于不同 endpoint/config 的交叉 Task namespace 隔离证明，也不替代 OpenCode
三协议成功、Provider failure、retry/recovery、完整四 Harness conformance 或 L5/L6 验收。
