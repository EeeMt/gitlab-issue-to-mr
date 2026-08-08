# Multi-Harness 接入调试与通用经验

> 2026-08-03 起 · 目标主机 192.168.50.129 · 首个第二 Harness：Codex CLI 0.146.0
> (`codex-package-x86_64-unknown-linux-musl.tar.gz`)
> 相关计划：[Phase 2 实施计划](superpowers/plans/2026-08-01-multi-harness-phase-2-codex-integration.md)、
> [多 Harness 总计划](superpowers/plans/2026-08-01-multi-harness-engine-roadmap.md)

本文记录把真实 Codex CLI 接入 Codify 多 Harness 框架、从「任务失败」到「harness 端到端跑通」的每一层根因与修复。
**多数根因是多 Harness 抽象层的隐性单 Harness 假设**，不是 Codex 特有——对后续接入任意新 Harness
（如 OpenCode）同样适用；因此叙述按**通用接入断层**组织，Codex 的 CLI 行为差异收敛为[专项](#2-codex-专项cli-行为差异)。
核心教训：**执行事实必须来自冻结 Snapshot / Runtime Bundle manifest；每一层修复都回到这一不变量。**

## 0. 核心不变量（接入任何 Harness 都必须满足）

1. **执行事实来自冻结 Snapshot / Bundle manifest**——adapter、harness_key、bundle manifest、session 路径、CLI 路径等，任何一处硬编码单一 harness 都要回到 snapshot。
2. **权威结果文件单一来源是 `CODIFY_HARNESS_RESULT_FILE`**——translator 写它，adapter `normalize_result` 必须读它；runner 的 `CODIFY_HARNESS_OUTPUT_FILE` 只是 legacy CLI stdout，不可用于 canonical 判定。
3. **worker 容器即沙箱**——`container-boundary` 是生产默认（与 Claude 一致），不依赖容器内 bwrap/userns；`sandboxed` 只是硬化 Host 的可选纵深防御。
4. **Harness 只产代码，delivery 统一 commit + MR**——delivery 必须区分「harness 产生的已发布 commit」与「无任何变更」。
5. **异步 SQLAlchemy 永远不直接访问懒加载关系**——用 `sa_inspect().unloaded` 检查或显式 `selectinload`。

## 1. 通用接入断层清单（新增 Harness 时逐项排查）

### 1.1 执行路径硬编码单 harness

- **现象**：创建时指定 `harness_key=codex`，日志却出现 `[ci-claude]` 标记（Task 479/480/481）。
- **根因**：`worker_task_lifecycle.create_execute_container` 里 `create_task_attempt(..., harness_key="claude")` 硬编码；container env 的 `CODIFY_HARNESS_KEY` 来自 attempt，所以永远跑 claude。
- **修复**：`create_task_attempt` 从 Task 冻结 Snapshot 读 `harness_key`，按该 key 从 bundle manifest 取 adapter version；`load_task_worker_runtime` 把 snapshot 挂到 `task.worker_profile_snapshot` 供下游安全读取。

### 1.2 Bundle manifest 只声明单 harness

- **现象**：Task 的 `harness_snapshot.adapter_version` 为 None。
- **根因**：`build_runtime_bundle` 硬编码 `"adapters": {"claude": {...}}`，即使源码 manifest 已加新 adapter，bundle manifest 也不含 → 冻结读不到。
- **修复**：`build_runtime_bundle` 遍历源码 manifest 的全部 adapters，为每个计算 digest。

### 1.3 CLI 脚本路径与 bundle archive 映射不一致

- **现象**：`Harness Adapter command is unavailable: .../legacy/codex-run.sh`。
- **根因**：adapter 返回的路径带 `deploy/` 前缀，而 bundle 内映射已去掉（`.../worker-entrypoint/legacy/...`）。
- **修复**：adapter 返回 `${CODIFY_ORCHESTRATION_DIR}/worker-entrypoint/legacy/<run-script>`；同时设置对应 translator 路径（与 claude.sh 一致）。

### 1.4 懒加载关系导致 greenlet 错误

- **现象**：访问 snapshot 关系抛 `MissingGreenlet`；单任务 GET 用 `.load_only(...)` 只加载旧列，新 harness 列未加载。
- **根因**：新代码用 `getattr(task, "worker_profile_snapshot", None)` 直接访问懒加载关系；异步 session 里懒加载在非 async 上下文触发同步 IO。
- **修复**：所有对 snapshot 的读取用 `sa_inspect(task)` 检查 `"worker_profile_snapshot" in inspection.unloaded`，已加载才读；session upsert/resume 解析整体 try/except 兜底（永不阻塞执行）；GET 的 `load_only` 补上全部 harness 冻结列。

### 1.5 run 脚本 exit 语义：canonical 结果权威

- **现象**：`harness-result.json` 为 `status=completed, success=True`、agent 也写了文件，但 `worker_finalization exit_code=1`，无 commit/MR。
- **根因**：harness 完成 turn 后可能因良性 item 错误（如 fallback model metadata）返回非零 exit；run 脚本把 CLI 的 exit 直接当作 harness 结果 → 提前退出。
- **修复**：run 脚本在 raw 流含 turn-terminal（如 `"turn.completed"`）时返回 0（canonical result 是权威），让共享 delivery 提交 agent 改动。**注意**：此修复后需重新验证 commit+MR。

### 1.6 normalize_result 读错文件

- **现象**：harness 成功 + 任务 failed + 无 commit；`normalize_result=1` 但 `harness.completed` 已发射。
- **根因**：runner 把 legacy CLI stdout 重定向到 `CODIFY_HARNESS_OUTPUT_FILE`（新 CLI stdout 为空 → 0 字节）；normalize 误读它而非 translator 写的 `CODIFY_HARNESS_RESULT_FILE`（见不变量 2）。
- **修复**：`normalize_result` 改读 `CODIFY_HARNESS_RESULT_FILE`。claude adapter 一直读对了，故不受影响。

### 1.7 Delivery 语义：harness 已提交的 commit vs 无变更

- **根因 1**：harness exec 会自己 `git commit`+`git push`（工作区变干净、HEAD 已发布）；`repo_has_unpublished_local_head` 只覆盖「未发布本地 commit」，已发布场景落入 else → `require_changes=true` 时 `exit 1`。
- **修复 1**：新增 `repo_work_branch_ahead_of_base`，main.sh 加 `elif` 分支 `push_harness_commit`（push `|| true` 容忍已发布 + `write_existing_commit_delivery_metadata` 复用 harness commit 并写 metadata，backend 据此更新 MR）。
- **验证**（Task 498/499/501）：`run.completed(success)`，commit `cd659f6e`/`5e8ae97`/`1f2772c1`，MR !5；canonical 流 `run.started(sandbox=container-boundary) → … → harness.completed → delivery.started → delivery.completed → worker.finalization(exit 0) → run.completed`。
- **根因 2**：`repo_work_branch_ahead_of_base` 不能以 base 分支为基线——同一 issue 分支已有历史任务 commit，会误判「新任务无变更也算已提交」并复用旧 commit（Task 500：provider 429 无新变更却「成功」复用 `5e8ae97`）。
- **修复 2**：基线改为 repository 准备时记录的 `REPO_REMOTE_WORK_SHA`（任务开始时的 work 分支 head），只检测**本次任务期间**新产生的 commit；无新 commit 的任务正确失败。

### 1.8 Session 隔离与 resume

- **跨 Harness 隔离**（Task 514/515/516）：claude fresh 产生 session A，codex continue 的 `input_session_id` 为空（不复用 claude session）。修复 `record_task_output_session` 懒加载 fallback 导致 session 误记到错误 lineage 的 bug（显式 `db.refresh` snapshot + 仅在 claude 时写 `issue.claude_session_id`）。
- **resume**（Task 521/522）：注入 `CODIFY_RESUME_SESSION`（仅 continue），run 脚本用 `codex exec resume <session>`；**CLI home 挂 issue-shared 持久目录**（如 `/opt/codify-issue-shared/codex-home`）使 session transcript 跨任务保存（`rollout-*.jsonl` 可见）；resume 任务 `input_session` 非空且 `run.completed(success)`。

### 1.9 Harness 切换约束（决策 4）

- `session_mode=continue` 且显式传 `harness_key` 时，后端校验必须等于 issue 最近 lineage 的 `harness_key`（`get_issue_latest_harness_key`），否则 422「续跑会话必须沿用原 Harness；切换请勾选使用新会话执行」。
- 前端 `TaskFormDrawer` 在非新会话且有现有 lineage 时禁用 harness 选择器（`harnessLocked`）；Issue 详情返回 `current_harness` 供前端默认。

### 1.10 取消 / 超时路径与 harness 无关

- **取消**（Task 509/511）：RUNNING 时 cancel → `status=cancelled`、容器清理、scheduler 记 `Task was cancelled during execution; removing container`。finalizer 的 cancelled 分支 harness 无关（Task 469 已先在 claude 验证）。
- **超时**（Task 513）：全局 `task_timeout=60` → `status=failed`、error `Task timed out after 60s`、容器终止（测试后恢复原值）。
- **推论**：这两个路径在任一 harness 验证通过即可，无需每个 harness 都重跑。

## 2. Codex 专项（CLI 行为差异）

Codex 是首个第二 Harness，其固有 CLI 行为与 Codify 抽象不同，需由 adapter 的 config/prepare 显式收敛到冻结事实。

### 2.1 环境准备

- Codex 包解压到宿主 `/opt/codify/codex`（含 `bin/codex`、`codex-resources/bwrap`、`codex-path/rg`）。
- Worker Profile 挂载 `{host_path:/opt/codify/codex, container_path:/opt/codify-codex, mode:ro}`，`enabled_harnesses=["claude","codex"]`，`harness_runtimes.codex = {source:host_mount, executable_path:/opt/codify-codex/bin/codex, version:0.146.0, binary_digest:<sha256>}`。
- 新增 openai_responses Provider 指向 OpenAI 兼容端点（如 DeepSeek，模型 `deepseek-v4-flash`）。
- 验证命令：创建 Task（`harness_key=codex`），看 `error_message` / archive 里 `harness-events/codex.jsonl`。

### 2.2 不读 `OPENAI_BASE_URL` → 需 config.toml

- **现象**：报 `failed to connect to websocket: ... wss://api.openai.com/v1/responses`。
- **根因**：codex 不读 `OPENAI_BASE_URL`（Responses API 走 websocket），默认连 OpenAI。
- **修复**：`codex_adapter_prepare_config` 在 `CODEX_HOME/config.toml` 显式写 `model_provider` + `[model_providers.codify]`（base_url/wire_api/env_key），指向冻结 Snapshot 端点。

### 2.3 默认模型

- **现象**：DeepSeek 报 `you passed gpt-5.6-sol`，支持的是 `deepseek-v4-pro/flash`。
- **根因**：config.toml 设了 `model_provider` 但没设顶层 `model`，codex 用默认模型。
- **修复**：config.toml 加 `model = "${OPENAI_MODEL}"`。

### 2.4 bwrap 依赖 userns → 容器边界模式决策

- **现象**：`bwrap: No permissions to create a new namespace ... kernel does not allow non-privileged user namespaces`。
- **根因**：worker 容器未允许非特权 userns，bwrap 无法工作。**这触发了 2.8 沙箱决策**。
- **决策（2026-08-03）**：worker 容器本身就是每任务隔离沙箱（与 Claude 一致），`container-boundary` 为生产默认，不需要容器内 bwrap/userns。`codex_adapter_prepare_config` 从冻结 Snapshot 的 `CODIFY_HARNESS_SANDBOX_MODE` 映射：`container-boundary`→`danger-full-access`，`sandboxed`（Profile 收紧）→`read-only`；`CODIFY_CODEX_SANDBOX` 仍可显式覆盖。最终策略冻结进 Snapshot 并写入 `run.started` 供审计。

### 2.5 固有 commit+push → 写文件模式

Codex 的 `exec` 会自己 `git commit`+`git push`，与「harness 只产代码、delivery 统一提交」不一致。查官方文档确认两点后改为「写文件模式」：

- **官方设计**：`workspace-write` 沙箱下 `.git/` 恒只读 → codex 无法 commit。但 worker 容器不允许非特权 userns，`workspace-write` 的 bwrap 让**所有命令失败**（实测 Task 503 failed），所以容器边界模式仍用 `danger-full-access`。
- **方案**：`danger-full-access`（容器即边界）+ `execpolicy.rules` 明确 `forbidden` `git commit/push/add/rm/mv/reset/revert/merge/checkout/branch/stash/init` + `approval_policy="never"`（CI 无人值守）。codex 只写工作区文件、不碰 git；Codify delivery 检测到变更后统一 commit。

### 2.6 运行用户降权

- **问题**：codex exec 最初以容器 root 运行（audit 流 event.jsonl/harness-result.json 由 bootstrap 有意 root-owned+644，translator 需以 root 写 canonical 事件），工作区/`.git` 因此 root-owned；delivery 以 codify（uid 1000）commit 报 `insufficient permission ... .git/objects`（Task 504 failed），并引入条件 chown hack。
- **根治**：收编到与 Claude 一致的模式——`codex-run.sh` 用 FIFO + 后台进程重构（镜像 ci-claude.sh）：CLI 子进程经 `CODIFY_CODEX_RUN_AS`（codify-run-as）降为 codify 运行，FIFO 写端 fd 由 root 父 shell 的重定向打开、降权子进程继承；translator 留在 root 上下文逐行消费 FIFO，写 root-owned raw 流/canonical 事件。这样产出天生 codify-owned。
- **配套**：交付前无条件 chown 删除；保留 reuse 路径的**条件 chown 作为 legacy 安全网**（`find /workspace/.git -user root` 仅在存在 root-owned 条目时才归一化，覆盖旧 root-owned 工作区遗留 shard；新 run 无 root-owned 对象则跳过）。`codex-run.sh` 不用 `set -m`（避免 timeout 组信号够不到 CLI 导致孤儿进程），并校验 `CODIFY_CODEX_RUN_AS` 必须为可执行绝对路径。
- **验证**：写文件 → `delivery.completed(exit 0)` → `run.completed(success)`；`.git` 全程 codify-owned。与 Claude 行为/运行用户完全一致。

## 3. 经验总结

1. **「执行事实来自冻结 Snapshot / Bundle manifest」是多 Harness 的核心不变量**——所有硬编码的单一 harness（adapter、harness_key、bundle manifest、session 路径、CLI 路径）都要回到 snapshot。
2. **异步 SQLAlchemy 里永远不要直接访问懒加载关系**——用 `sa_inspect().unloaded` 检查，或显式 `selectinload`。
3. **外部 CLI 行为差异是调试主战场**——不读标准 env、默认模型、依赖 userns 等，都要通过 adapter 的 config/prepare 显式收敛到冻结事实。
4. **归档的 `harness-events/<harness>.jsonl` 是定位 CLI 层问题的第一现场**——每次失败先看它。
5. **沙箱决策（2026-08-03）**——worker 容器即沙箱，容器边界模式是生产默认（与 Claude 一致）；容器内 bwrap/userns 不是前提。
6. **权威结果文件单一来源是 `CODIFY_HARNESS_RESULT_FILE`**——translator 写它、adapter `normalize_result` 必须读它；与 `CODIFY_HARNESS_OUTPUT_FILE` 混淆时任务静默 failed。
7. **Harness 可能自己 commit+push**——delivery 必须区分「harness 已发布的 commit」（`repo_work_branch_ahead_of_base` 复用）与「无任何变更」（`require_changes` 才失败）；工作区干净不代表失败。

## 4. 验证命令速查

```bash
# 创建 codex 任务
curl -s -b /tmp/codify_cookies.txt -X POST http://<host>:8880/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"issue_id":83,"user_prompt":"<prompt>","priority":1,"provider_id":7,"harness_key":"codex","task_mode":"execute","session_mode":"fresh","require_changes":true}'

# 看 harness 结果（canonical 权威）
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/tasks/<id>/archive/download -o /tmp/t.tar.gz
tar xzf /tmp/t.tar.gz harness-events/codex.jsonl harness-result.json
head -c 1200 harness-events/codex.jsonl   # CLI 层原始事件/报错
python3 -m json.tool harness-result.json    # success/usage/session

# 看结构化终态
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/tasks/<id>/logs
```

> 完整回归步骤见 [dev-env-core-regression.md](./dev-env-core-regression.md)；API 细节见 [dev-env-api-regression.md](./dev-env-api-regression.md)。
