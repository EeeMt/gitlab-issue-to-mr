# 模型凭据交付方式：受限 legacy 风险接受

> 状态：已接受（受限）· 2026-08-05
> 关联：[多 Harness 总计划决策 11](../superpowers/plans/2026-08-01-multi-harness-engine-roadmap.md)、
> [Phase 2 退出门禁「凭据交付」](../superpowers/plans/2026-08-01-multi-harness-phase-2-codex-integration.md)、
> [worker-harness-contract-v1.md](../architecture/worker-harness-contract-v1.md)、
> [多 Harness 设计 §11](../superpowers/specs/2026-07-31-multi-harness-engine-design.md)

## 1. 现状（本文件接受的模式）

- **交付方式**：模型 Provider 的长期 key 在任务执行时从数据库 `provider.api_key`（静态加密）解密，
  以容器环境变量注入 worker 容器（`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`，来源链见
  `backend/app/core/worker_runtime.py::_resolve_provider_environment_values`）。
- **`credential_ref` 抽象**：`ModelCredential` 生命周期（active/retired/revoked）、`credential_ref`
  冻结进 Task Snapshot、`resolve_task_credential` 的 fail-closed 语义均已实现，但**运行时接线延后**
  ——容器 env 目前仍读取 `provider.api_key` 迁移遗留值，不经过 `resolve_task_credential`。
- **不是默认**：本模式只适用于已明确配置的受信内网 Profile 与开发验证环境；**不可信仓库或公网
  生产 Profile 不得默认使用**（见 §3 范围限制）。

## 2. 已落地的缓解措施

| 缓解 | 说明 |
|---|---|
| 静态加密 | `api_key` 加密存储，解密仅发生在调度器注入 env 时 |
| 日志/事件清洗 | `scrub_sensitive_data` 覆盖 GitLab PAT、Anthropic `sk-ant-*`/`sk-cp-*`/`sk-api-*`、OpenAI `sk-proj-*`/通用 `sk-*`、`Bearer` token、Google/GitHub/HuggingFace/Slack token 前缀、`api_key`/`env_key` 配置形态 |
| Snapshot 不含 secret | `model_endpoint_snapshot` 是 secret-free 结构，Task Snapshot / runtime archive 不落长期 key |
| 隔离低权限 key | 开发验证环境使用独立的低权限模型 key，不共享生产凭据 |
| 只读仓库挂载 | worker 容器内仓库只读挂载，harness 只能写 `CODEX_HOME`/agent-state 密封目录 |

## 3. 接受范围与边界

- **接受**：受信内网 / 开发验证环境，Operator 明确选择该 Profile 运行任务。
- **不接受**：不可信仓库、公网生产 Profile、或可被任意提交代码影响的仓库。此类场景必须等
  `resolve_task_credential` 运行时接线（短期 token / Broker）后再启用，不允许以本文档作为默认放行依据。
- **不留长期回退**：本模式是过渡，不是长期目标。接入 `resolve_task_credential`（或模型出口代理/
  凭据 Broker，让 worker 只持有短期、任务级、最小权限 token）后，本文档即失效并被撤销。

## 4. 到期复查与升级路径

- 本文档随 Phase 2 生产候选冻结；升级路径（接线 `resolve_task_credential`）每季度复查一次。
- 触发条件：接入 Broker/短期 token、或任何公网/不可信仓库 Profile 提出使用长期容器 key 的需求时，
  必须先完成接线或重新评估本文档。
- 撤销条件：worker 容器 env 不再注入长期 key（改为 `credential_ref` 解析 / 短期 token），
  且不可信仓库 Profile 在 legacy 模式下 fail closed。

## 5. 引用

- Roadmap 决策 11：「长期模型密钥不默认进入仓库代码可继承的进程」。
- worker-harness-contract-v1.md §凭据：long-lived secrets 应经 proxy/Broker/task token 中介，
  legacy container env 是有记录的受限过渡，不是安全默认。
- 设计 §11：MVP 若沿用容器内密钥必须标记显式风险接受，使用独立低权限凭据、限制模型和额度、
  缩短有效期、限制网络出口，并确保日志清洗覆盖 OpenAI/Anthropic/自定义 Provider token 形态。
