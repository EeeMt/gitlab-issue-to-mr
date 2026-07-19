# Worker Volume Mounts — 完整梳理

使用独立项目运行时镜像并在启动时注入 Codify 工具时，另见
[Mounted Worker Kits](worker-kits.md)。

## 概述

Worker 容器有两类持久挂载和一类运行时输入：

1. **Daemon-local Issue Workspace** — Git 仓库、Claude 会话和 issue 级共享目录
2. **静态/自定义挂载** — Maven 缓存、CA 证书、用户自定义 volume
3. **Docker API Runtime Bundle** — prompt、Worker 脚本、前序摘要和 CI failure bundle；不使用宿主机共享挂载

Issue 创建时必须显式选择 Worker Profile，之后该 Issue 的普通任务、重试任务和 CI
自动修复任务都固定使用同一个 Worker。任务创建和编辑接口不接受 Worker 切换。

---

## 1. Persistent Workspace（持久化工作区）

### 配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `worker_workspace_host_path` | `WORKER_WORKSPACE_HOST_PATH` | `/opt/codify-workspaces` | 每个 Docker daemon 自己的本地工作目录根路径，必须是非空绝对路径 |
| `worker_workspace_retention_days` | `WORKER_WORKSPACE_RETENTION_DAYS` | `14` | 正常任务 workspace 保留天数 |
| `worker_failed_workspace_retention_days` | `WORKER_FAILED_WORKSPACE_RETENTION_DAYS` | `30` | 失败任务 workspace 保留天数（配置已定义，清理逻辑尚未区分） |

路径通过部署环境变量 `WORKER_WORKSPACE_HOST_PATH` 配置，修改后需要重新创建 Backend
和 Scheduler 容器。该路径由目标 Docker daemon 解析；多个 Worker 主机可以使用相同路径
字符串，但目录内容彼此独立，不需要 NFS。

Backend/Scheduler 只把独立的本地 `CI_FAILURE_BUNDLE_HOST_PATH` bind 到配置根目录下的
`ci-failures/`，用于保存和读取控制面输入。它不需要与远程 Worker 主机共享；Scheduler
会把 CI 输入连同 prompt 和脚本一起通过 Docker API 上传。

### 远程 Docker daemon

Worker Profile 可以选择系统默认 Docker，也可以配置独立的 `docker_host` 和 TLS
CA、客户端证书、客户端密钥文件路径。Docker 目标及 TLS 路径会写入任务级 Worker
快照；Profile 后续修改不会改变已经创建的任务。

Docker 连接接受 `unix://`、`tcp://` 和 `https://` 端点；不接受会被
Docker SDK 当作明文连接的 `http://`，也暂不支持需要额外运行时依赖的 `ssh://` 或
仅适用于 Windows 的 `npipe://`。远程 `tcp://` 建议同时配置完整 TLS 文件路径。

Backend/Scheduler 不读写远程 Issue 工作目录。状态查询、人工删除和定时清理都在
Issue 固定的 Worker daemon 上启动短生命周期维护容器完成。任务输入先写入内存 tar，
再通过 Docker `put_archive` 注入已创建但尚未启动（`created`）的任务容器，上传成功后
才启动容器。

默认 Compose 将 `${DOCKER_CERTS_HOST_PATH:-/opt/codify-docker-certs}` 只读挂载到
Backend 和 Scheduler 的 `/opt/codify-docker-certs`。管理员可按 daemon 分目录保存证书，
并在 Worker Profile 中配置容器内绝对路径，例如：

```text
/opt/codify-docker-certs/arm64/ca.pem
/opt/codify-docker-certs/arm64/cert.pem
/opt/codify-docker-certs/arm64/key.pem
```

Profile 自定义 volume 的 `host_path` 同样由目标 Docker host 解释，必须预先存在于该主机。

### 路径构建

`build_issue_workspace_paths()`（`worker_workspace.py:19`）基于 `{host_path}/project-{project_id}/issue-{issue_id}` 生成：

```
/opt/codify-workspaces/
└── project-{project_id}/
    └── issue-{issue_id}/
        ├── repo/                  → 容器内 /workspace
        ├── claude/                → 容器内 /home/codify/.claude
        ├── shared/                → 容器内 /opt/codify-issue-shared
        └── meta/                  → 容器内 /opt/codify-issue-meta
```

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `.../issue-{id}/repo` | `/workspace` | `rw` | Git 仓库，跨任务复用 |
| `.../issue-{id}/claude` | `/home/codify/.claude` | `rw` | Claude CLI 会话状态，跨任务复用 |
| `.../issue-{id}/shared` | `/opt/codify-issue-shared` | `rw` | 同一 issue 内多个 task 共享的通用可变空间 |
| `.../issue-{id}/meta` | `/opt/codify-issue-meta` | `rw` | Worker/Profile 归属标记，供运维和安全清理使用 |

`/tmp/codify-runtime` 不再挂载宿主机目录。它属于任务容器本身：输入由 Docker API
上传，日志、归档和 metadata 在容器删除前通过 Docker API 拉回。这里也不能再声明
tmpfs：`put_archive` 写入 `created` 容器后，启动时才挂载的 tmpfs 会遮蔽已上传文件。

`meta/ownership` 记录当前 workspace 的运行 UID/GID。升级后首次复用旧目录时，如果
该标记缺失或 UID/GID 已变化，entrypoint 会对 repo、Claude 会话和 shared 目录执行
一次递归 `chown`，完成后后续任务只调整顶层目录权限，避免重复遍历大型目录。

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

1. issue workspace 的 repo/Claude/shared/meta 挂载
2. 任务 Worker 快照中的自定义挂载

自定义挂载不能覆盖 `/workspace`、`/home/codify/.claude`、
`/opt/codify-issue-shared`、`/opt/codify-issue-meta` 或 `/tmp/codify-runtime`；
其中 `meta` 和 runtime 的子路径也保留给 Codify 协议文件。

旧的全局 Worker 字段保留一个版本，作为迁移来源和兼容面。新的执行路径读取 `task_worker_profile_snapshots`。

### 容器内行为（`entrypoint.worker.sh`）

Issue 创建时可以固定仓库初始化策略：

- `git_clone_depth = null`：完整历史克隆，保持兼容行为
- `git_clone_depth = 1..10000`：按指定深度浅克隆；初次克隆只取 base branch
- `git_clone_filter = "blob:none"`：启用 partial clone，先取提交和目录结构，按需下载文件内容；
  可与完整历史或浅历史独立组合

这些字段创建后不可修改，确保同一 Issue 的持久化 workspace 和重试任务使用一致策略。
Worker Profile 自定义环境变量不能覆盖对应的 `CODIFY_GIT_CLONE_DEPTH` 和
`CODIFY_GIT_CLONE_FILTER`。使用 mounted-kit 的 Worker Profile 必须先升级到
worker-kit `0.3.0` 或更高版本；Backend 会拒绝把优化策略绑定到旧版 kit。

浅克隆使用 `--single-branch --branch "${BASE_BRANCH}"`，但 checkout 前会额外探测远端
Issue 分支；如果分支已经由早期任务推送，则通过显式 refspec 拉取并基于该分支继续，
不会错误地从 base branch 重新创建。复用 workspace 时会在一次远端探测后，用一次
定向 fetch 同步 base/work 两个精确 ref，并继续保留深度限制，不再执行重复 pull。
本地和远端工作分支相同时直接继续；远端仅追加提交时使用 `merge --ff-only`；本地仅
领先时保留未推送提交。双方历史分叉、浅历史无法证明关系，或脏 workspace 遇到远端
推进时，Worker 会明确失败并记录双方 SHA，不会自动 merge、rebase 或 force-push。
如果本地领先但接续任务没有产生新的工作区修改，Worker 仍会把已经保留的本地提交
推送到远端，并把该提交写入任务 finalization 和 task metadata，不会把“无新增修改”
误判成“无需交付”。
Worker 还会比较 fetch 前后的 remote-tracking SHA；远端分支被删除或被强制回退时会
停止任务，避免自动重建分支或重新推回人工移除的提交。
最终 push 会先确认本地历史仍包含任务启动时的远端 SHA，再用该 SHA 作为精确 lease
执行原子更新。lease 不用于允许非 fast-forward 覆盖，只用于拒绝任务执行期间发生的
远端追加、删除或回退；失败日志会记录任务启动时、当前远端和本地 SHA。若 push
命令返回非零，但复查发现远端已经等于本地提交，则按幂等成功继续，覆盖“服务端完成
更新后连接中断”的不确定结果。
如果 `/workspace` 不含 `.git` 但已有其他文件，Worker 会拒绝 clone，不会把持久化内容
当作失败残留删除。`blob:none` 初次 clone 失败时只会在已确认初始目录为空后清理该次
失败留下的内容，并自动回退为不带 filter 的同深度 clone。服务端返回成功但明确提示
忽略 filter 时，不会重复 clone；Worker 会清除误导性的 promisor 配置，将
`fallback` 记录为 `filter_ignored`，并把 `effective_filter` 记录为空。

控制台以 `[repo]` 前缀记录请求策略、workspace 新建/复用、已有 Issue 分支恢复、
filter 回退、实际 shallow/filter 状态、耗时、当前提交和 pack 大小。例如：

```text
[repo] prepare workspace=new strategy=shallow depth=50 filter=blob:none
[repo] remote_refs base=9f01... work=13ac... default=main
[repo] fetching existing work branch=codify/issue-123 depth=50 requested_filter=blob:none
[repo] sync work_branch=codify/issue-123 relation=remote_ahead action=fast_forward dirty=false local=8b21... remote=13ac...
[repo] actual_state shallow=true effective_filter=blob:none
[repo] ready action=clone elapsed_ms=842 branch=codify/issue-123 commit=1a2b3c4 pack_size=18.4 MiB fallback=none
```

同一组结构化数据写入 `/tmp/codify-runtime/repository-preparation.json`，并随任务
runtime archive 下载，便于对大型仓库初始化耗时、实际生效策略和回退情况进行审计。
产物包含 `status`、`phase` 和 `exit_code`；clone/fetch/checkout 失败时也会在退出
钩子中生成。即使 Claude 尚未启动、`event.jsonl` 和 `runtime.json` 尚不存在，也会
归档 `console.log` 与该结构化产物。
仍保留脏分支保护：当前 workspace 在其他分支且存在未提交修改时，任务会拒绝切换。

### 清理机制

- **定时清理**：Scheduler 每 6 小时按数据库中的 `workspace_last_used_at` 查询过期 Issue，排除存在 active task 或尚未完成容器引用收口的 Issue，再通过其固定 Worker 的 Docker API 删除目录
- **手动清理**：`DELETE /api/tasks/{task_id}/workspace` 检查整个 Issue 无 active task 且无保留容器引用后，在固定 Worker 上删除 workspace
- **状态查询**：`GET /api/tasks/{task_id}/workspace` 在固定 Worker 上检查 issue 目录和 `repo/.git`
- **归属保护**：新目录包含 `meta/owner`；如果标记存在但与 Issue/Worker 不匹配，删除操作拒绝执行
- **容器引用收口**：任务容器确认删除后立即清空 `task.container_id`；Scheduler 每分钟限批次重试终态容器的日志最终化和删除，启动恢复也会复核旧版本遗留引用
- **匿名 volume**：删除任务、恢复、取消和维护容器时统一启用 Docker 的 `v=true`，清理自定义镜像通过 `VOLUME` 声明产生的匿名 volume；repo/Claude/shared/meta 都是 bind mount，不会因此删除宿主目录

### 启用条件

`worker_workspace_host_path` 非空 **且** task 和 issue 均存在。运行任务必须满足该条件。
Scheduler 不要求能够直接访问远程路径，只要求目标 daemon 能将该本地路径 bind mount
到任务容器。

### 持久化主提示词

每个新任务在数据库事务内保存运行指令模板快照和最终渲染提示词。Worker 准备容器时
把最终内容写入内存 tar 中的：

```text
codify-runtime/task-prompt.md
```

该 tar 通过 Docker API 上传后映射为容器内稳定路径：

```text
/tmp/codify-runtime/task-prompt.md
```

容器环境变量 `CODIFY_TASK_PROMPT_FILE` 只携带上述稳定路径。`entrypoint.worker.sh` 要求文件存在且非空，然后复制到 `/tmp/claude_prompt.txt` 供 `ci-claude.sh` 使用；不会根据 `USER_PROMPT` 或 `TASK_MODE` 回退拼装主提示词。`USER_PROMPT` 仍保留用于任务元数据、MR 描述和后处理。

这项协议要求 Backend/Scheduler 与匹配的 Worker image 作为一个兼容版本协同部署。Scheduler 必须先完成 pending/queued 历史任务的提示词回填，再允许新 Worker 执行任务。

---

## 2. Session Storage（Claude 会话持久化）

### 路径生成

Claude 会话目录固定属于 issue workspace：

```
/opt/codify-workspaces/project-{project_id}/issue-{issue_id}/claude
```

`session_storage_root` 和已有 issue 上的旧 `session_storage_path` 字段仅用于历史数据兼容；
新执行链路不允许关闭持久 workspace，也不会为新任务选择 legacy session 路径。

### 挂载映射

| 宿主机路径 | 容器内路径 | 模式 | 用途 |
|-----------|-----------|------|------|
| `.../issue-{issue_id}/claude` | `/home/codify/.claude` | `rw` | Claude CLI 会话文件（`.jsonl`） |

### 会话生命周期

1. Issue 创建时生成 workspace 内的 `session_storage_path`
2. Worker 启动容器时挂载到 `/home/codify/.claude`
3. 如果 Issue 已有 `claude_session_id`，worker 将其作为 `RESUME_SESSION` 传入容器，脚本再用该值恢复 Claude 会话
4. 容器退出后，entrypoint 从 session 文件中提取 `CODIFY_SESSION_ID`，worker 将其写回 `issue.claude_session_id`
5. 下次任务继续复用同一会话，实现多轮对话的跨任务延续

### 与 Workspace 的关系

Session Storage 归属于 issue workspace：
- `repo/` 存放 Git 仓库和未提交状态
- `claude/` 存放 Claude CLI 会话状态
- `shared/` 存放同一 issue 内跨 task 复用的用户配置缓存或工具状态
- 清理 issue workspace 也会删除 Claude resume context

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

Backend/Scheduler 容器只需要控制面自己的持久目录。Issue workspace 路径由目标 Docker
daemon 解析，不要求挂载进 Backend/Scheduler，也不要求不同 Worker 主机共享：

| 宿主机路径 | 容器内路径 | 使用者 | 用途 |
|-----------|-----------|--------|------|
| `${CI_FAILURE_BUNDLE_HOST_PATH:-/opt/codify-ci-failures}` | `${WORKER_WORKSPACE_HOST_PATH}/ci-failures` | Backend、Scheduler | 暂存控制面收集的 CI failure bundle |
| `/opt/codify-archives` | `/opt/codify-archives` | Backend | 写入运行时归档文件 |
| `/var/run/docker.sock` | `/var/run/docker.sock` | Backend、Scheduler | 访问本机 Docker；远程 Worker 使用 Profile 的 endpoint |

CI bundle 会被打入任务 runtime tar，再通过 Docker API 上传到目标容器，因此
`ci-failures/` 也不需要与 Worker daemon 共享。

---

## 7. 完整挂载决策流程图

```
build_container_volumes(settings, issue, task=task)
│
├─ build_issue_workspace_paths()
│   ├─ volumes[repo_path]    = {bind: /workspace,             mode: rw}
│   ├─ volumes[claude_path]  = {bind: /home/codify/.claude,  mode: rw}
│   ├─ volumes[shared_path]  = {bind: /opt/codify-issue-shared, mode: rw}
│   └─ volumes[meta_path]    = {bind: /opt/codify-issue-meta, mode: rw}
│
└─ worker_volume_mounts_parsed (含 CA cert 自动注入)
    └─ 遍历每个 mount → volumes[host_path] = {bind: container_path, mode}

build_task_runtime_archive(...)
└─ Docker put_archive('/tmp') → /tmp/codify-runtime（容器内非持久层）
```

---

## 8. 相关文件索引

| 文件 | 职责 |
|------|------|
| `backend/app/config.py` | 所有配置项定义和默认值 |
| `backend/app/api/config_runtime.py` | 运行时配置读写 + 校验 |
| `backend/app/api/issues.py` | Issue 创建时固化 Worker 归属 |
| `backend/app/core/worker_workspace.py` | 计算 daemon-local workspace 路径 |
| `backend/app/core/worker_workspace_remote.py` | 通过目标 Docker daemon 查询和删除 workspace |
| `backend/app/core/worker_runtime.py` | 组装持久挂载和 runtime tar |
| `backend/app/core/worker_results.py` | `finalize_archive()` 拉取运行时归档 |
| `backend/app/core/worker_task_lifecycle.py` | 创建未启动容器、上传 runtime tar、启动并收尾 |
| `backend/app/core/docker_client.py` | 容器生命周期和 `put_archive()` |
| `backend/app/scheduler.py` | 按数据库状态调度远程 workspace 清理 |
| `deploy/docker-compose.yml` | Backend 宿主目录挂载 |
| `deploy/worker-entrypoint/bootstrap.sh` | 容器内 workspace 初始化和归属标记 |
| `deploy/worker-entrypoint/repository-helpers.sh` | 仓库交付、准备阶段失败产物和计时辅助 |
| `deploy/worker-entrypoint/repository.sh` | clone/fetch、分支关系判定和 checkout |
