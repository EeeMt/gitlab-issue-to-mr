# Worker Volume Mounts — 完整梳理

## 概述

Worker 容器有三种挂载来源：

1. **Persistent Workspace** — 跨任务持久化的 Git 仓库和运行时目录
2. **Session Storage** — Claude 会话文件持久化
3. **静态/自定义挂载** — Maven 缓存、CA 证书、用户自定义 volume

所有挂载通过 `build_container_volumes()`（`backend/app/core/worker_runtime.py:191`）组装，最终传给 Docker SDK 的 `client.containers.run(volumes=...)`。

---

## 1. Persistent Workspace（持久化工作区）

### 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `worker_workspace_host_path` | `""`（空，功能关闭） | 宿主机根路径，例如 `/opt/codify-workspaces` |
| `worker_workspace_retention_days` | `14` | 正常任务 workspace 保留天数 |
| `worker_failed_workspace_retention_days` | `30` | 失败任务 workspace 保留天数（配置已定义，清理逻辑尚未区分） |

配置方式：环境变量 `WORKER_WORKSPACE_HOST_PATH` 或通过 `/api/config/runtime` 运行时修改。

### 路径构建

`build_issue_workspace_paths()`（`worker_workspace.py:19`）基于 `{host_path}/project-{project_id}/issue-{issue_id}` 生成：

```
/opt/codify-workspaces/
└── project-{project_id}/
    └── issue-{issue_id}/
        ├── repo/                  → 容器内 /workspace
        └── runtime/
            └── task-{task_id}/    → 容器内 /tmp/codify-runtime
```

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `.../issue-{id}/repo` | `/workspace` | `rw` | Git 仓库，跨任务复用 |
| `.../issue-{id}/runtime/task-{id}` | `/tmp/codify-runtime` | `rw` | 任务运行时产物（event.jsonl、runtime.json、console.log） |

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

`worker_workspace_host_path` 非空 **且** task 和 issue 均存在。否则不创建 workspace volume，容器仍可正常运行（使用临时文件系统）。

---

## 2. Session Storage（Claude 会话持久化）

### 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `session_storage_root` | `/var/codify/sessions` | 会话文件根目录 |

### 路径生成

创建 Issue 时（`backend/app/api/issues.py:144`）：

```python
issue.session_storage_path = f"{settings.session_storage_root}/{issue.id}/claude"
```

实际路径：`/var/codify/sessions/{issue_id}/claude`

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `/var/codify/sessions/{issue_id}/claude` | `/home/codify/.claude` | `rw` | Claude CLI 会话文件（`.jsonl`） |

### 会话生命周期

1. Issue 创建时生成 `session_storage_path` 和 `claude_session_id`
2. Worker 启动容器时挂载到 `/home/codify/.claude`
3. 如果 Issue 已有 `claude_session_id`，entrypoint 用 `claude -r {session_id}` 恢复会话
4. 容器退出后，entrypoint 从 session 文件中提取 `CODIFY_SESSION_ID`，worker 将其写回 `issue.claude_session_id`
5. 下次任务继续复用同一会话，实现多轮对话的跨任务延续

### 与 Workspace 的关系

Session Storage 和 Persistent Workspace 是两套独立机制：
- Session Storage 存的是 Claude CLI 的对话状态（`.jsonl` 文件）
- Workspace 存的是 Git 仓库和构建产物
- Session Storage 始终基于 Issue（不需要 `worker_workspace_host_path`），路径在 Issue 创建时就确定了

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

### 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `maven_cache_host_path` | `""` | Maven 本地仓库宿主路径，例如 `/opt/maven-repo` |
| `maven_settings_host_path` | `""` | Maven settings.xml 宿主路径 |

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `{maven_cache_host_path}` | `/home/codify/.m2/repository` | `rw` | Maven 依赖缓存，跨任务共享 |
| `{maven_settings_host_path}` | `/home/codify/.m2/settings.xml` | `ro` | Maven 私有仓库配置 |

定义在 `worker_runtime.py:15-16`：

```python
_MAVEN_CACHE_CONTAINER_PATH = "/home/codify/.m2/repository"
_MAVEN_SETTINGS_CONTAINER_PATH = "/home/codify/.m2/settings.xml"
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
├─ maven_cache_host_path 非空?
│   └─ YES → volumes[host_path] = {bind: /home/codify/.m2/repository, mode: rw}
│
├─ maven_settings_host_path 非空?
│   └─ YES → volumes[host_path] = {bind: /home/codify/.m2/settings.xml, mode: ro}
│
├─ worker_volume_mounts_parsed (含 CA cert 自动注入)
│   └─ 遍历每个 mount → volumes[host_path] = {bind: container_path, mode}
│
├─ worker_workspace_host_path 非空 && issue && task?
│   └─ YES → build_issue_workspace_paths()
│       ├─ volumes[repo_path]    = {bind: /workspace,          mode: rw}
│       └─ volumes[runtime_path] = {bind: /tmp/codify-runtime, mode: rw}
│
└─ issue.session_storage_path 非空?
    └─ YES → volumes[session_storage_path] = {bind: /home/codify/.claude, mode: rw}
```

---

## 8. 相关文件索引

| 文件 | 职责 |
|------|------|
| `backend/app/config.py` | 所有配置项定义和默认值 |
| `backend/app/api/config_runtime.py` | 运行时配置读写 + 校验 |
| `backend/app/api/issues.py:144` | Issue 创建时生成 `session_storage_path` |
| `backend/app/core/worker_workspace.py` | Workspace 路径构建、删除、过期清理 |
| `backend/app/core/worker_runtime.py` | `build_container_volumes()` 组装所有挂载 |
| `backend/app/core/worker_results.py` | `finalize_archive()` 拉取运行时归档 |
| `backend/app/core/worker_task_lifecycle.py` | 调用 volume 构建和 archive 收尾 |
| `backend/app/core/docker_client.py` | `create_container()` 将 volumes 传给 Docker API |
| `backend/app/scheduler.py` | Scheduler 定时 workspace 清理 |
| `deploy/docker-compose.yml` | Backend 宿主目录挂载 |
| `deploy/entrypoint.worker.sh` | 容器内 /workspace 复用逻辑 |
