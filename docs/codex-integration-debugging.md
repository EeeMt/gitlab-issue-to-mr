# Codex 真实集成端到端调试记录

> 2026-08-03 · 目标主机 192.168.50.129 · Codex CLI 0.146.0(`codex-package-x86_64-unknown-linux-musl.tar.gz`)
> 相关计划:[Phase 2 实施计划](superpowers/plans/2026-08-01-multi-harness-phase-2-codex-integration.md)、
> [多 Harness 总计划](superpowers/plans/2026-08-01-multi-harness-engine-roadmap.md)

本文记录把真实 Codex CLI 接入 Codify 多 Harness 框架过程中,从「任务失败」到「harness 端到端跑通」
的每一层根因与修复。**核心教训:多 Harness 抽象层的隐性单 Harness 假设 + 真实 CLI 的行为差异,
是逐层暴露的;每一层修复都要回到「执行事实来自冻结 Snapshot / Runtime Bundle manifest」这一不变量。**

## 环境准备

- Codex 包解压到宿主 `/opt/codify/codex`(含 `bin/codex`、`codex-resources/bwrap`、`codex-path/rg`)。
- Worker Profile 11 挂载 `{host_path:/opt/codify/codex, container_path:/opt/codify-codex, mode:ro}`,
  `enabled_harnesses=["claude","codex"]`,`harness_runtimes.codex = {source:host_mount, executable_path:/opt/codify-codex/bin/codex, version:0.146.0, binary_digest:<sha256>}`。
- 新增 openai_responses Provider 指向 DeepSeek OpenAI 兼容端点(`https://api.deepseek.com`,模型 `deepseek-v4-flash`)。
- 验证命令:创建 Task(`harness_key=codex`),看 `error_message` / archive 里 `harness-events/codex.jsonl`。

## 失败层与修复(按出现顺序)

### 1. 执行路径硬编码 `harness_key="claude"`

**现象**:Task 479/480/481 的日志出现 `[ci-claude]` 标记,即使创建时 `harness_key=codex`。

**根因**:`worker_task_lifecycle.create_execute_container` 里 `create_task_attempt(..., harness_key="claude")`
是硬编码的;container env 的 `CODIFY_HARNESS_KEY` 来自 attempt,所以永远跑 claude。

**修复**:`create_task_attempt` 从 Task 冻结 Snapshot 读 `harness_key`,并按该 key 从 bundle manifest
取 adapter version。配套:`load_task_worker_runtime` 把 snapshot 挂到 `task.worker_profile_snapshot`,
下游才能安全读取。

### 2. greenlet 懒加载回归(`MissingGreenlet` / `greenlet_spawn has not been called`)

**现象**:任务 GET 与执行在访问 snapshot 关系时抛 `MissingGreenlet`;执行时在 flush 中触发。

**根因**:新加的 harness/session 代码用 `getattr(task, "worker_profile_snapshot", None)` 直接访问
懒加载关系。SQLAlchemy 异步 session 里,懒加载在非 async 上下文触发同步 IO → greenlet 错误。
单任务 GET 还用 `.load_only(...)` 只加载了旧列,新 harness 列未加载。

**修复**:所有对 snapshot 的读取都用 `sa_inspect(task)` 检查 `"worker_profile_snapshot" in inspection.unloaded`,
已加载才读;session upsert/resume 解析整体 try/except 兜底(永不阻塞执行)。GET 的 `load_only` 补上
全部 harness 冻结列。

### 3. Runtime Bundle manifest 只声明 claude

**现象**:Task 的 `harness_snapshot.adapter_version` 为 None。

**根因**:`build_runtime_bundle` 硬编码 `"adapters": {"claude": {...}}`,即使源码 manifest 已加
`adapters.codex`,bundle manifest 也不含 codex → 冻结读不到 codex adapter。

**修复**:`build_runtime_bundle` 遍历源码 manifest 的全部 adapters,为每个计算 digest。

### 4. codex-run.sh 路径错误

**现象**:`Harness Adapter command is unavailable: .../legacy/codex-run.sh`。

**根因**:`codex_adapter_build_command` 返回的路径与 bundle archive 映射不符。bundle 里
`deploy/worker-entrypoint/legacy/codex-run.sh` 映射为 `.../worker-entrypoint/legacy/codex-run.sh`
(去 `deploy/` 前缀),但 adapter 返回了 `.../deploy/worker-entrypoint/legacy/...`。

**修复**:`codex_adapter_build_command` 返回 `${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/codex-run.sh`;
同时设置 `CODIFY_CODEX_TRANSLATOR` 路径(与 claude.sh 一致)。

### 5. codex 连到默认 `api.openai.com`

**现象**:`codex.jsonl` 报 `failed to connect to websocket: ... wss://api.openai.com/v1/responses`。

**根因**:codex CLI 不读 `OPENAI_BASE_URL`(Responses API 走 websocket),默认连 OpenAI。

**修复**:`codex_adapter_prepare_config` 在 `CODEX_HOME/config.toml` 显式写
`model_provider` + `[model_providers.codify]`(base_url/wire_api/env_key),指向冻结 Snapshot 端点。

### 6. codex 用了默认模型 `gpt-5.6-sol`

**现象**:DeepSeek 报 `you passed gpt-5.6-sol`,支持的是 `deepseek-v4-pro/flash`。

**根因**:config.toml 设了 `model_provider` 但没设顶层 `model`,codex 用默认模型。

**修复**:config.toml 加 `model = "${OPENAI_MODEL}"`。

### 7. bwrap 沙箱无法创建 namespace

**现象**:codex 执行命令报 `bwrap: No permissions to create a new namespace ... kernel does not
allow non-privileged user namespaces`。

**根因**:worker 容器未允许非特权 userns,bwrap 无法工作。**这是 2.8 沙箱的真实卡点。**

**修复(dev 风险接受)**:`codex_adapter_prepare_config` 设 `sandbox_mode = "danger-full-access"`
(容器即边界),用 `CODIFY_CODEX_SANDBOX` 可覆盖为 `read-only`。**注意**:这是显式风险接受,
不是静默放宽;生产必须硬化容器启用 userns/bwrap(见计划 2.8 fail-closed)。

### 8. harness 成功但任务 failed、commit_sha=null

**现象**:`harness-result.json` 是 `status=completed, success=True`,agent 也写了文件,但
`worker_finalization exit_code=1`,无 commit/MR。

**根因**:codex 在完成 turn 后可能因良性 item 错误(如 fallback model metadata)返回非零 exit;
`codex-run.sh` 把 codex 的 exit 直接当作 harness 结果 → `codify_harness_run` 返回非零 → main.sh 提前退出。

**修复**:`codex-run.sh` 在 raw 流含 `"turn.completed"` 时返回 0(canonical result 是权威),
让共享 delivery 提交 agent 的改动。**注意**:此修复后需重新验证 commit+MR。

## 经验总结

1. **「执行事实来自冻结 Snapshot / Bundle manifest」是多 Harness 的核心不变量**——所有被硬编码的
   `claude`(adapter、harness_key、bundle manifest、session 路径、CLI 路径)都要回到 snapshot。
2. **异步 SQLAlchemy 里永远不要直接访问懒加载关系**——用 `sa_inspect().unloaded` 检查,或显式 selectinload。
3. **外部 CLI 行为差异是调试主战场**——codex 不读 `OPENAI_BASE_URL`、默认模型、bwrap 依赖 userns,
   这些都要通过 adapter 的 config/prepare 显式收敛到 Codify 的冻结事实。
4. **归档的 `harness-events/<harness>.jsonl` 是定位 CLI 层问题的第一现场**——每次失败先看它。
5. **沙箱安全是硬边界**——容器内核能力(bwrap/userns)决定 codex 能否用真沙箱;dev 可显式风险接受
   容器边界模式,生产必须硬化容器。

## 验证命令速查

```bash
# 创建 codex 任务
curl -s -b /tmp/codify_cookies.txt -X POST http://<host>:8880/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"issue_id":83,"user_prompt":"<prompt>","priority":1,"provider_id":7,"harness_key":"codex","task_mode":"execute","session_mode":"fresh","require_changes":true}'

# 看 harness 结果(canonical 权威)
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/tasks/<id>/archive/download -o /tmp/t.tar.gz
tar xzf /tmp/t.tar.gz harness-events/codex.jsonl harness-result.json
head -c 1200 harness-events/codex.jsonl   # CLI 层原始事件/报错
python3 -m json.tool harness-result.json    # success/usage/session

# 看结构化终态
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/tasks/<id>/logs
```
