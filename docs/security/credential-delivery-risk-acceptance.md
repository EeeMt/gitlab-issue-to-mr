# 模型凭据交付方式：受限 legacy 风险接受

> 状态：已接受（受限）· 2026-08-05
> 关联：[多 Harness 总计划决策 11](../superpowers/plans/2026-08-01-multi-harness-engine-roadmap.md)、
> [Phase 2 退出门禁「凭据交付」](../superpowers/plans/2026-08-01-multi-harness-phase-2-codex-integration.md)、
> [worker-harness-contract-v1.md](../architecture/worker-harness-contract-v1.md)、
> [多 Harness 设计 §11](../superpowers/specs/2026-07-31-multi-harness-engine-design.md)

## 当前状态（2026-09-05）

本文档仍然保留，作为旧 Task Snapshot 与兼容回退路径的历史、受限风险接受；它不是当前
V2 candidate 的完整安全签署，也不授权公网或不可信仓库使用长期容器密钥。当前 V2 已将
secret-free endpoint 与 `credential_ref` 冻结进 Task Snapshot，并在 Worker 启动前经
`resolve_task_credential` 解析；缺失或 revoked 凭据 fail closed，已有 retry 才允许使用
retired 凭据。详见当前 [R4.5 安全与发布审计](../superpowers/evidence/2026-09-04-open-harness-v2-r4.5-security-release-audit.md)。

这项 runtime 接线并不等于本文档已撤销：解析后的 secret 仍会交付到 Worker 环境变量，且
没有显式 `credential_ref` 的旧 Snapshot 仍保留 Provider-key legacy fallback。容器内长期
secret 的替换、外部 GitLab/OAuth 最小权限、账户控制、轮换与撤销仍需独立 owner/security
签署后，才能扩大安全边界。

## 1. 现状（本文件接受的模式）

- **legacy 交付方式**：对旧 Snapshot 或兼容回退路径，模型 Provider 的长期 key 在任务执行时从数据库
  `provider.api_key`（静态加密）解密，以容器环境变量注入 worker 容器（`ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY`）。这就是本文件接受的 legacy 模式，并非当前 V2 新 Snapshot 的首选解析路径。
- **当前 V2 `credential_ref` 路径**：`ModelCredential` 生命周期（active/retired/revoked）、
  `credential_ref` 冻结进 Task Snapshot、`resolve_task_credential` 的 fail-closed 语义已经进入
  Worker runtime；但解析后的 secret 仍以环境变量交付，因此尚未满足短期 token/Broker 或完整
  外部权限签署所要求的安全边界。
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
- **不接受**：不可信仓库、公网生产 Profile、或可被任意提交代码影响的仓库。仅有
  `resolve_task_credential` runtime 接线并不足以扩大范围；在 Worker 仍接收长期环境变量，且
  外部权限、账户控制、轮换和撤销尚未完成 owner/security 签署前，不允许以本文档作为放行依据。
- **不留长期回退**：本模式是过渡，不是长期目标。只有在所有受支持的旧 Snapshot 不再需要
  `provider.api_key` fallback、Worker 不再接收长期 key（改为短期 token / 模型出口代理 / 凭据
  Broker），并完成新的安全边界签署后，本文档才可撤销。

## 4. 到期复查与升级路径

- 本文档随 Phase 2 生产候选冻结；当前 V2 的 `credential_ref` runtime 路径应在后续 owner
  审计中继续复查，但不把本次接线本身记录为撤销条件已满足。
- 触发条件：接入 Broker/短期 token、任何公网/不可信仓库 Profile 提出使用长期容器 key 的需求，
  或需要移除旧 Snapshot 的 Provider-key fallback 时，必须先完成安全复查与边界签署。
- 撤销条件：Worker 容器 env 不再注入长期 key（改为任务级短期 token / Broker / 受控模型出口），
  所有旧 Snapshot 的兼容处理已有明确替代方案，且不可信仓库 Profile 在新边界下 fail closed。

## 5. 引用

- Roadmap 决策 11：「长期模型密钥不默认进入仓库代码可继承的进程」。
- worker-harness-contract-v1.md §凭据：long-lived secrets 应经 proxy/Broker/task token 中介，
  legacy container env 是有记录的受限过渡，不是安全默认。
- 设计 §11：MVP 若沿用容器内密钥必须标记显式风险接受，使用独立低权限凭据、限制模型和额度、
  缩短有效期、限制网络出口，并确保日志清洗覆盖 OpenAI/Anthropic/自定义 Provider token 形态。
