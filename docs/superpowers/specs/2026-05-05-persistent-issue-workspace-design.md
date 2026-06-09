# Persistent Issue Workspace Design

## 背景

当前 worker 容器启动后在容器内创建 `/workspace`，clone 仓库后执行任务。任务结束、失败或取消后，容器会被删除，`/workspace` 也随容器销毁。

这会导致两个问题：

1. 任务执行到一半失败或被取消时，未提交改动丢失，无法从现场继续。
2. 大仓库每次任务都重新 clone，执行成本较高。

产品设定是：同一个 issue 同一时间只能有一个 task 执行。因此可以将 workspace 从容器临时目录升级为 issue 级持久工作区，让同一 issue 的后续 task 复用现场。

## 目标

- 同一 issue 的 task 严格串行执行。
- task 失败或取消后，workspace 现场保留。
- 后续 task 可以从同一 issue workspace 继续工作。
- runtime 文件和归档文件不进入 git 工作区。
- worker 容器仍可及时销毁，下载归档继续由 backend 持久化保存。

## 非目标

- 不支持同一 issue 多个 task 并发写同一个 workspace。
- 不把 token、`.git-credentials`、Claude 会话配置写入 repo workspace。
- 不把 `event.jsonl`、`runtime.json`、`console.log` 或 archive 存在 `/workspace` 内。

## 目录结构

宿主机：

```text
/opt/codify-workspaces/
  project-{project_id}/
    issue-{issue_id}/
      repo/
      runtime/
        task-{task_id}/
```

容器挂载：

```text
/opt/codify-workspaces/project-{project_id}/issue-{issue_id}/repo
  -> /workspace

/opt/codify-workspaces/project-{project_id}/issue-{issue_id}/runtime/task-{task_id}
  -> /tmp/codify-runtime
```

归档持久化仍使用现有目录：

```text
/opt/codify-archives/task-{task_id}-runtime-archive.tar.gz
```

`/tmp/codify-runtime/task-{task_id}-runtime-archive.tar.gz` 只作为容器内临时文件。backend 在容器删除前通过 Docker `get_archive` 复制到 `/opt/codify-archives`，下载接口读取宿主机持久化文件。

## 执行锁

当前 scheduler 使用进程内 `_running_issues` 阻止同 issue 并发执行。这个约束只在单 backend/scheduler 进程内有效，不是系统级严格保证。

持久 workspace 需要先加强 issue 级执行锁。建议新增表：

```text
issue_execution_locks
  issue_id      primary key
  task_id       not null
  acquired_at   not null
  heartbeat_at  nullable
```

启动任务时原子抢锁：

```text
BEGIN
INSERT INTO issue_execution_locks(issue_id, task_id, acquired_at)
VALUES (...)
ON CONFLICT DO NOTHING

如果插入失败：跳过该 task
如果插入成功：将 task.status 更新为 RUNNING
COMMIT
```

释放锁时机：

- task completed
- task failed
- task cancelled
- worker 启动失败
- crash recovery 判定 task 不再运行

`_running_issues` 可以保留作为进程内快速判断，但不能作为唯一约束。

## Worker 启动流程

backend 创建容器前计算 workspace 路径：

```text
workspace_root = settings.worker_workspace_host_path
issue_workspace = {workspace_root}/project-{project_id}/issue-{issue_id}
repo_path = {issue_workspace}/repo
runtime_path = {issue_workspace}/runtime/task-{task_id}
```

创建目录并设置权限后挂载到容器。

entrypoint 中 clone 逻辑改为幂等：

```bash
if [ -d /workspace/.git ]; then
    cd /workspace
    git remote set-url origin "${GIT_REPO_URL}"
    git fetch origin
else
    git clone "${GIT_REPO_URL}" /workspace
    cd /workspace
fi
```

分支处理规则：

1. 当前分支是 `BRANCH_NAME`：保留 workspace 现场并继续。
2. 当前分支不是 `BRANCH_NAME` 且 workspace clean：允许 checkout。
3. 当前分支不是 `BRANCH_NAME` 且 workspace dirty：任务失败，提示需要清理 workspace 或人工处理。

## 任务语义

建议明确 UI/API 语义：

- `failed`: 保留 workspace，可继续。
- `cancelled`: 保留 workspace，可继续或清理。
- `completed`: 可按 TTL 清理 workspace。
- `retry`: 默认复用 issue workspace。
- `retry clean`: 清空 issue workspace 后重新 clone。

后续可以在任务详情页增加 workspace 状态：

- workspace 是否存在
- 当前分支
- dirty 文件数量
- 最近关联 task id
- 清理 workspace 操作

## Runtime 与 Archive

`ci-claude.sh` 继续写：

```text
/tmp/codify-runtime/event.jsonl
/tmp/codify-runtime/runtime.json
/tmp/codify-runtime/console.log
```

entrypoint 生成：

```text
/tmp/codify-runtime/task-{task_id}-runtime-archive.tar.gz
```

backend 实时投影读取 `/tmp/codify-runtime/event.jsonl` 和 `/tmp/codify-runtime/console.log`。

backend finalization 在容器删除前执行：

```text
container.get_archive("/tmp/codify-runtime/task-{task_id}-runtime-archive.tar.gz")
-> /opt/codify-archives/task-{task_id}-runtime-archive.tar.gz
-> TaskRunArchive DB record
```

这样 worker 容器可以及时销毁，下载能力不依赖容器生命周期。

## 清理策略

建议增加后台清理任务：

- completed workspace 保留 N 天后删除。
- failed/cancelled workspace 默认保留更久，或直到用户清理。
- runtime/task 目录在 archive 成功持久化后可按 TTL 删除。
- 清理前确认 issue 没有 active lock。

## 配置项

新增配置：

```text
WORKER_WORKSPACE_HOST_PATH=/opt/codify-workspaces
WORKER_WORKSPACE_RETENTION_DAYS=14
WORKER_FAILED_WORKSPACE_RETENTION_DAYS=30
```

当 `WORKER_WORKSPACE_HOST_PATH` 为空时，保持当前临时容器 workspace 行为，便于灰度发布。

## 实施步骤

1. 新增 `issue_execution_locks` 表和 acquire/release helper。
2. scheduler 启动 task 前抢 DB lock，结束后释放。
3. cancel、failure、crash recovery 补齐锁释放。
4. 增加 `worker_workspace_host_path` 配置。
5. `build_container_volumes` 增加 issue repo 和 task runtime 挂载。
6. entrypoint 支持已有 `/workspace/.git` 的复用路径。
7. backend archive/timeline 路径保持 `/tmp/codify-runtime`。
8. 增加 workspace 状态 API 和清理 API。
9. 增加后台 TTL 清理。

## 风险与缓解

- 风险：锁泄漏导致 issue 永久无法执行。
  - 缓解：crash recovery 根据 task/container 状态修复锁。

- 风险：workspace dirty 且分支不匹配。
  - 缓解：拒绝自动切换，提示清理或人工处理。

- 风险：多 backend/scheduler 实例并发。
  - 缓解：DB lock 是唯一启动执行门禁。

- 风险：workspace 占用磁盘。
  - 缓解：TTL 清理和手动清理接口。

- 风险：runtime 文件误提交。
  - 缓解：runtime 挂载到 `/tmp/codify-runtime`，不在 `/workspace` 内。

## 推荐结论

在同 issue task 严格串行的产品设定下，issue 级持久 workspace 是推荐方案。落地顺序应先加强 issue execution lock，再启用 workspace 挂载。这样可以保留失败现场、支持继续执行，同时避免并发写同一 repo 带来的文件冲突。

## Implementation Notes

Implemented in phases:

- Database-backed `issue_execution_locks` provides the authoritative issue execution gate.
- Worker workspace persistence is optional and controlled by `WORKER_WORKSPACE_HOST_PATH`.
- Runtime files and archives remain outside `/workspace` and are read from `/tmp/codify-runtime`.
- Backend persists downloadable archives to `/opt/codify-archives` before worker containers are removed.
