# Worker Volume Mounts — 完整梳理

## 概述

Worker 容器有三种挂载来源：

1. **Persistent Workspace** — 跨任务持久化的 Git 仓库、运行时目录和 issue 级共享目录
2. **Session Storage** — Claude 会话文件持久化
3. **静态/自定义挂载** — Maven 缓存、CA 证书、用户自定义 volume

所有挂载通过 `build_container_volumes()`（`backend/app/core/worker_runtime.py:191`）组装，最终传给 Docker SDK 的 `client.containers.run(volumes=...)`。

---

## 1. Persistent Workspace（持久化工作区）

### 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `worker_workspace_host_path` | `WORKER_WORKSPACE_HOST_PATH` | `/opt/codify-workspaces` | 宿主机根路径（绝对路径）；设为空字符串可关闭持久 workspace |
| `worker_workspace_retention_days` | `WORKER_WORKSPACE_RETENTION_DAYS` | `14` | 正常任务 workspace 保留天数 |
| `worker_failed_workspace_retention_days` | `WORKER_FAILED_WORKSPACE_RETENTION_DAYS` | `30` | 失败任务 workspace 保留天数（配置已定义，清理逻辑尚未区分） |

配置方式：环境变量（推荐）或通过 `/api/config/runtime` 运行时修改（当前前端暂无 UI 入口）。

### 路径构建

`build_issue_workspace_paths()`（`worker_workspace.py:19`）基于 `{host_path}/project-{project_id}/issue-{issue_id}` 生成：

```
/opt/codify-workspaces/
└── project-{project_id}/
    └── issue-{issue_id}/
        ├── repo/                  → 容器内 /workspace
        ├── claude/                → 容器内 /home/codify/.claude
        ├── runtime/
        │   └── task-{task_id}/    → 容器内 /tmp/codify-runtime
        └── shared/                → 容器内 /opt/codify-issue-shared
```

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `.../issue-{id}/repo` | `/workspace` | `rw` | Git 仓库，跨任务复用 |
| `.../issue-{id}/claude` | `/home/codify/.claude` | `rw` | Claude CLI 会话状态，跨任务复用 |
| `.../issue-{id}/runtime/task-{id}` | `/tmp/codify-runtime` | `rw` | 任务运行时产物（包括 `task-prompt.md`、event.jsonl、runtime.json、console.log） |
| `.../issue-{id}/shared` | `/opt/codify-issue-shared` | `rw` | 同一 issue 内多个 task 共享的通用可变空间 |

### Shared 目录

`shared/` 只提供 issue 级共享挂载，不内置任何语言或包管理器语义。需要使用 pip、npm 等缓存时，通过已有 Worker environment variables 配置显式指定路径，例如：

```text
PIP_CACHE_DIR=/opt/codify-issue-shared/cache/pip
NPM_CONFIG_CACHE=/opt/codify-issue-shared/cache/npm
```

环境变量值不会做 shell 展开，建议直接写完整绝对路径。现有环境变量 key 校验只允许大写，因此 npm 使用 `NPM_CONFIG_CACHE`。

## Worker Profiles

新任务不再直接从全局 runtime config 读取自定义挂载、环境变量、Worker 脚本或运行指令默认值。任务创建时会解析 Worker Profile，并保存任务级 Worker 快照。

运行时 volume 顺序保持为：

1. issue workspace 挂载
2. Claude session/runtime/shared 挂载
3. 任务 Worker 快照中的自定义挂载

旧的全局 Worker 字段保留一个版本，作为迁移来源和兼容面。新的执行路径读取 `task_worker_profile_snapshots`。

### 容器内行为（`entrypoint.worker.sh`）

```bash
# 如果 /workspace/.git 已存在则复用，否则 clone
if [ -d /workspace/.git ]; then
    cd /workspace
    git remote set-url origin "${GIT_REPO_URL}"
    git fetch origin
else
    git clone "${GIT_REPO_URL}" /workspace
    cd /workspace
fi

# 脏分支保护：如果有未提交变更且分支不匹配，拒绝切换
WORKSPACE_CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ -n "${WORKSPACE_CURRENT_BRANCH}" ] && [ "${WORKSPACE_CURRENT_BRANCH}" != "${BRANCH_NAME}" ]; then
    WORKSPACE_DIRTY=$(git status --porcelain)
    if [ -n "${WORKSPACE_DIRTY}" ]; then
        echo "ERROR: Workspace has uncommitted changes on branch ${WORKSPACE_CURRENT_BRANCH}"
        exit 1
    fi
fi
```

### 清理机制

- **定时清理**：Scheduler 每 6 小时（`_WORKSPACE_CLEANUP_INTERVAL_SECONDS = 21600`）扫描 `worker_workspace_host_path` 下的 issue 目录，删除 mtime 超过 `retention_days` 的目录
- **手动清理**：通过 `DELETE /api/tasks/{task_id}/workspace` 删除整个 issue 的 workspace
- **状态查询**：`GET /api/tasks/{task_id}/workspace` 查看 workspace 状态

### 启用条件

`worker_workspace_host_path` 非空 **且** task 和 issue 均存在。运行任务现在必须满足该条件：Backend 在创建容器前需要把数据库中的 `rendered_prompt` 写入 task runtime，缺少 workspace/runtime 路径会在 Docker 容器创建前直接失败。

### 持久化主提示词

每个新任务在数据库事务内保存运行指令模板快照和最终渲染提示词。Worker 准备容器时将最终内容逐字节写入：

```text
runtime/task-{task_id}/task-prompt.md
```

该文件随 runtime volume 映射为：

```text
/tmp/codify-runtime/task-prompt.md
```

容器环境变量 `CODIFY_TASK_PROMPT_FILE` 只携带上述稳定路径。`entrypoint.worker.sh` 要求文件存在且非空，然后复制到 `/tmp/claude_prompt.txt` 供 `ci-claude.sh` 使用；不会根据 `USER_PROMPT` 或 `TASK_MODE` 回退拼装主提示词。`USER_PROMPT` 仍保留用于任务元数据、MR 描述和后处理。

这项协议要求 Backend/Scheduler 与匹配的 Worker image 作为一个兼容版本协同部署。Scheduler 必须先完成 pending/queued 历史任务的提示词回填，再允许新 Worker 执行任务。

---

## 2. Session Storage（Claude 会话持久化）

### 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `session_storage_root` | `/var/codify/sessions` | 会话文件根目录 |

### 路径生成

当 `worker_workspace_host_path` 启用时，Claude 会话目录是 issue workspace 的一部分：

```
/opt/codify-workspaces/project-{project_id}/issue-{issue_id}/claude
```

当 `worker_workspace_host_path` 设为空字符串并关闭持久 workspace 时，回退到旧版 session 路径：

```
{session_storage_root}/{issue_id}/claude
```

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `.../issue-{issue_id}/claude` 或 `{session_storage_root}/{issue_id}/claude` | `/home/codify/.claude` | `rw` | Claude CLI 会话文件（`.jsonl`） |

### 会话生命周期

1. Issue 创建时根据 workspace 配置生成 `session_storage_path`
2. Worker 启动容器时挂载到 `/home/codify/.claude`
3. 如果 Issue 已有 `claude_session_id`，worker 将其作为 `RESUME_SESSION` 传入容器，脚本再用该值恢复 Claude 会话
4. 容器退出后，entrypoint 从 session 文件中提取 `CODIFY_SESSION_ID`，worker 将其写回 `issue.claude_session_id`
5. 下次任务继续复用同一会话，实现多轮对话的跨任务延续

### 与 Workspace 的关系

当 `worker_workspace_host_path` 启用时，Session Storage 归属于 issue workspace：
- `repo/` 存放 Git 仓库和未提交状态
- `runtime/task-{task_id}/` 存放单个任务的运行时文件
- `claude/` 存放 Claude CLI 会话状态
- `shared/` 存放同一 issue 内跨 task 复用的用户配置缓存或工具状态
- 清理 issue workspace 也会删除 Claude resume context

当 `worker_workspace_host_path` 为空时，不创建 issue workspace，Session Storage 使用 `{session_storage_root}/{issue_id}/claude` legacy 路径：
- Claude 会话状态仍会挂载到 `/home/codify/.claude`
- legacy session 路径独立于 workspace cleanup
- workspace 状态查询和删除接口在该模式下不清理 Claude resume context

---

## 3. Runtime Archive（运行时归档）

### 概述

Archive 目录用于将容器内的运行时文件打包后持久化到宿主机，供用户下载。

### 容器内运行时代理

容器内的 entrypoint 在 `/tmp/codify-runtime/` 下生成三个文件：

| 文件 | 内容 |
|------|------|
| `event.jsonl` | Claude 工具调用事件流 |
| `runtime.json` | 运行时元数据 |
| `console.log` | 控制台输出 |

任务完成后，`ci-claude.sh` 将其打包为 `task-{task_id}-runtime-archive.tar.gz`。

### 归档拉取与存储

Worker 的 `finalize_archive()`（`worker_results.py:33`）从容器内拉取归档文件：

```python
stream, _stat_info = await asyncio.to_thread(
    container.get_archive,
    f"/tmp/codify-runtime/{archive_name}",
)
# 解包外层 tar，写到宿主机
archive_store = "/opt/codify-archives"
final_path = os.path.join(archive_store, archive_name)
```

### Compose 挂载

```yaml
# docker-compose.yml — backend 服务
- /opt/codify-archives:/opt/codify-archives
```

Backend 容器需要 `/opt/codify-archives` 来写入归档文件。由于 Docker SDK 的 `container.get_archive()` 返回的是流，Backend 把归档写到自己的文件系统（即宿主机的 `/opt/codify-archives`）。

### 归档元数据

归档信息存入 `task_run_archives` 表：

```python
db.add(TaskRunArchive(
    task_id=task_id,
    archive_name=archive_name,
    archive_path=final_path,
    archive_size_bytes=size,
))
```

---

## 4. Maven 缓存挂载

Maven 缓存和 `settings.xml` 不再有专用配置项。需要时使用通用
`worker_volume_mounts` 覆盖相同容器路径：

```json
[
  {
    "host_path": "/opt/maven-repo",
    "container_path": "/home/codify/.m2/repository",
    "mode": "rw"
  },
  {
    "host_path": "/opt/maven-settings.xml",
    "container_path": "/home/codify/.m2/settings.xml",
    "mode": "ro"
  }
]
```

---

## 5. 自定义 Volume 挂载

### 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `worker_volume_mounts` | `""` | JSON 数组，支持任意自定义挂载 |
| `worker_ca_cert_host_path` | `""` | CA 证书宿主路径（简化配置，自动生成 volume mount） |

### worker_volume_mounts 格式

```json
[
  {"host_path": "/opt/some-tool", "container_path": "/opt/tool", "mode": "ro"},
  {"host_path": "/opt/cache", "container_path": "/cache", "mode": "rw"}
]
```

通过 `/api/config/runtime` 配置，存储在 `system_config` 表中。

### CA 证书自动挂载

`worker_volume_mounts_parsed` 属性（`config.py:201`）自动将 `worker_ca_cert_host_path` 追加为：

```python
{
    "host_path": "{worker_ca_cert_host_path}",
    "container_path": "/etc/ssl/certs/custom-ca.crt",
    "mode": "ro",
}
```

如果 `worker_volume_mounts` 中已存在同路径的 CA 证书挂载，则替换而非重复。

---

## 6. Compose 层面的宿主机挂载汇总

Backend/Scheduler 容器需要以下宿主目录挂载（均在 `deploy/docker-compose.yml` 中定义）：

| 宿主机路径 | 容器内路径 | 使用者 | 用途 |
|-----------|-----------|--------|------|
| `/opt/codify-workspaces` | `/opt/codify-workspaces` | Backend | `os.makedirs()` 创建 workspace 目录 |
| `/opt/codify-archives` | `/opt/codify-archives` | Backend | 写入运行时归档文件 |
| `/var/run/docker.sock` | `/var/run/docker.sock` | Backend | Docker Engine API 通信 |

这些路径在容器内只是为了让 Backend 通过 Docker API 创建 worker 容器时，host_path 指向的路径在宿主机上确实存在。

---

## 7. 完整挂载决策流程图

```
build_container_volumes(settings, issue, task=task)
│
├─ worker_workspace_host_path 非空 && issue && task?
│   └─ YES → build_issue_workspace_paths()
│       ├─ volumes[repo_path]    = {bind: /workspace,          mode: rw}
│       ├─ volumes[claude_path]  = {bind: /home/codify/.claude, mode: rw}
│       ├─ volumes[runtime_path] = {bind: /tmp/codify-runtime, mode: rw}
│       └─ volumes[shared_path]  = {bind: /opt/codify-issue-shared, mode: rw}
│
├─ worker_workspace_host_path 为空 && issue.session_storage_path 非空?
│   └─ YES → volumes[session_storage_path] = {bind: /home/codify/.claude, mode: rw}
│
└─ worker_volume_mounts_parsed (含 CA cert 自动注入)
    └─ 遍历每个 mount → volumes[host_path] = {bind: container_path, mode}
```

---

## 8. 相关文件索引

| 文件 | 职责 |
|------|------|
| `backend/app/config.py` | 所有配置项定义和默认值 |
| `backend/app/api/config_runtime.py` | 运行时配置读写 + 校验 |
| `backend/app/api/issues.py:144` | Issue 创建时生成 workspace-local 或 legacy fallback 的 `session_storage_path` |
| `backend/app/core/worker_workspace.py` | Workspace 路径构建、删除、过期清理 |
| `backend/app/core/worker_runtime.py` | `build_container_volumes()` 组装所有挂载 |
| `backend/app/core/worker_results.py` | `finalize_archive()` 拉取运行时归档 |
| `backend/app/core/worker_task_lifecycle.py` | 调用 volume 构建和 archive 收尾 |
| `backend/app/core/docker_client.py` | `create_container()` 将 volumes 传给 Docker API |
| `backend/app/scheduler.py` | Scheduler 定时 workspace 清理 |
| `deploy/docker-compose.yml` | Backend 宿主目录挂载 |
| `deploy/entrypoint.worker.sh` | 容器内 /workspace 复用逻辑 |
