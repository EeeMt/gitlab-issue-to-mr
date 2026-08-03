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

**根因**:worker 容器未允许非特权 userns,bwrap 无法工作。**这触发了 2.8 的沙箱决策。**

**决策(2026-08-03)**:worker 容器本身就是每任务隔离沙箱,与 Claude harness 一致,**容器边界
模式(`container-boundary`)是生产默认**,不需要容器内 bwrap/userns。`codex_adapter_prepare_config`
从冻结 Snapshot 的 `CODIFY_HARNESS_SANDBOX_MODE` 映射:container-boundary→`danger-full-access`,
sandboxed(Profile 收紧)→`read-only`;`CODIFY_CODEX_SANDBOX` 仍可显式覆盖。最终策略冻结进
Snapshot 并写入 `run.started` 供审计。

### 8. harness 成功但任务 failed、commit_sha=null

**现象**:`harness-result.json` 是 `status=completed, success=True`,agent 也写了文件,但
`worker_finalization exit_code=1`,无 commit/MR。

**根因**:codex 在完成 turn 后可能因良性 item 错误(如 fallback model metadata)返回非零 exit;
`codex-run.sh` 把 codex 的 exit 直接当作 harness 结果 → `codify_harness_run` 返回非零 → main.sh 提前退出。

**修复**:`codex-run.sh` 在 raw 流含 `"turn.completed"` 时返回 0(canonical result 是权威),
让共享 delivery 提交 agent 的改动。**注意**:此修复后需重新验证 commit+MR。

### 9. 单 Host smoke 暴露的两层真实根因（2026-08-03，Task 493–498）

第 8 节修复后 codex 任务仍是 `harness 成功 + 任务 failed + 无 commit`。单 Host 加 DIAG
（`DIAG codex_run/harness_run` 写 console.log）定位到两层根因：

**根因 9a —— `codex_adapter_normalize_result` 读错文件。**
runner 把 legacy CLI 的 stdout 重定向到 `CODIFY_HARNESS_OUTPUT_FILE`
（`/tmp/codify-harness-output.json`，codex 的 stdout 为空 → 0 字节）；而权威 canonical
result 由事件 translator 写 `CODIFY_HARNESS_RESULT_FILE`（`/tmp/codify-runtime/harness-result.json`）。
codex 的 normalize 误读 `result_file` → 空文件 → `normalize_result=1`；由于
`harness.completed` 已发射，不补发 `harness.failed`，但 `codify_harness_run` 返回 1 →
main.sh `exit $RESULT`。claude adapter 正确读 `CODIFY_HARNESS_RESULT_FILE`，所以 claude 不受影响。
**修复**:`codex_adapter_normalize_result` 改读 `CODIFY_HARNESS_RESULT_FILE`（translator 写的权威文件）。

**根因 9b —— delivery 不识别“harness 已 commit+push”。**
codex exec 会自己 `git commit`+`git push`（工作区变干净、HEAD 已发布）。main.sh 的
`repo_has_unpublished_local_head` 只覆盖“未发布本地 commit”；已发布场景落入 else
“No changes made by Harness” → `require_changes=true` 时 `exit 1`。
**修复**:新增 `repo_work_branch_ahead_of_base`（`git rev-list base..HEAD` 非空），main.sh
加 `elif` 分支 `push_harness_commit`：push（`|| true` 容忍已发布）+ 
`write_existing_commit_delivery_metadata`（复用 harness commit 并写 metadata，backend 据此更新 MR）。

**验证（Task 498/499/501）**:`run.completed(success)`，commit `cd659f6e`/`5e8ae97`/`1f2772c1`，
MR !5；canonical 流 `run.started(sandbox=container-boundary) → … → harness.completed →
delivery.started → delivery.completed → worker.finalization(exit 0) → run.completed`。

**根因 9c —— `repo_work_branch_ahead_of_base` 不能以 base 为基线。**
最初用 `git rev-list ${BASE_BRANCH}..HEAD` 判“分支有新 commit”，但同一 issue 分支上
已存在历史任务（codex）的 commit，导致**新任务无任何变更时也被误判为“harness 已提交”**
并复用旧 commit（Task 500：claude provider 429 无新变更，却“成功”复用 codex 的 5e8ae97）。
**修复**:基线改为 repository 准备时记录的 `REPO_REMOTE_WORK_SHA`（任务开始时的 work 分支
head），只检测**本次任务期间**新产生的 commit；无新 commit 的任务正确落入 else 失败。

### 10. 让 Codex 与 Claude 一致：只写文件、由 Codify 统一提交（2026-08-04）

Codex 固有行为是 `exec` 会自己 `git commit`+`git push`，与 Codify「harness 只产代码、
delivery 统一提交」的模型不一致。查官方文档确认两点后改为「写文件模式」：

- **官方设计**:`workspace-write` 沙箱下 `.git/` 恒只读 → codex 无法 commit。但 worker 容器
  不允许非特权 userns，`workspace-write` 的 bwrap 让**所有命令失败**（实测 Task 503 failed），
  所以容器边界模式仍用 `danger-full-access`。
- **方案**:`danger-full-access`（容器即边界）+ `execpolicy.rules` 明确 `forbidden`
  `git commit/push/add/rm/mv/reset/revert/merge/checkout/branch/stash/init` + `approval_policy="never"`
  （CI 无人值守）。这样 codex 只写工作区文件、不碰 git；Codify 的 delivery 检测到变更后统一 commit。

**连带权限问题（`.git/objects` root-owned）**:codex exec 由 adapter 直接执行，以容器 root 运行，
早期任务写的 `.git/objects` 属主是 root；Codify delivery 以 codify 用户（uid 1000）commit 时
报 `insufficient permission ... .git/objects`（实测 Task 504 failed）。**修复**:repository 准备
完成时 `chown -R "${CODIFY_RUN_UID}:${CODIFY_RUN_GID}" /workspace/.git`，把持久 workspace 的
`.git` 归一化到执行用户。

**验证（Task 505/506）**:codex 写文件（+61 行变更）→ `delivery.completed(exit 0)` →
`run.completed(success)`，commit `c69e283c`/`070aefad`；自动 chown 生效（objects 从 root 归位
到 codify）。至此 Codex 与 Claude 的行为一致：**只生成代码，交付层统一 commit + MR**。

## 经验总结

1. **「执行事实来自冻结 Snapshot / Bundle manifest」是多 Harness 的核心不变量**——所有被硬编码的
   `claude`(adapter、harness_key、bundle manifest、session 路径、CLI 路径)都要回到 snapshot。
2. **异步 SQLAlchemy 里永远不要直接访问懒加载关系**——用 `sa_inspect().unloaded` 检查,或显式 selectinload。
3. **外部 CLI 行为差异是调试主战场**——codex 不读 `OPENAI_BASE_URL`、默认模型、bwrap 依赖 userns,
   这些都要通过 adapter 的 config/prepare 显式收敛到 Codify 的冻结事实。
4. **归档的 `harness-events/<harness>.jsonl` 是定位 CLI 层问题的第一现场**——每次失败先看它。
5. **沙箱决策(2026-08-03)**——worker 容器即沙箱,容器边界模式是生产默认(与 Claude 一致);
   容器内 bwrap/userns 不是前提,`sandboxed` 只是硬化 Host 的可选纵深防御,由 Profile 收紧。
6. **权威结果文件的单一来源是 `CODIFY_HARNESS_RESULT_FILE`**——translator 写它,adapter
   `normalize_result` 必须读它;runner 的 `result_file`（`CODIFY_HARNESS_OUTPUT_FILE`）只是
   legacy CLI stdout,不可用于 canonical 判定。两个路径不一致时任务静默 failed。
7. **Codex 会自己 commit+push**——delivery 必须区分“harness 产生的已发布 commit”
   （`repo_work_branch_ahead_of_base` 复用）与“无任何变更”（require_changes 才失败）。
   对 Codex 任务,工作区干净不代表失败。

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
