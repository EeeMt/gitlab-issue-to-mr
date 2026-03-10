# GitLab Issue to MR Bot - 设计方案

## 一、项目概述

在内网离线环境中，基于自建 GitLab 18 EE Ultimate 和 vLLM 部署的 MiniMax 大模型，构建一个自动化服务：用户在 GitLab Issue 中 `@bot` 后，系统自动根据 Issue 内容创建分支、调用 Claude CLI 实现需求、提交代码并发起 MR 关联 Issue。支持在 Issue 中反复 `@bot` 进行追加修改。同时提供 Web 管理后台，实现任务的可视化管理与调度控制。

## 二、环境前提

| 项 | 说明 |
|---|---|
| 网络 | 内网离线，无互联网 |
| GitLab | 自建 GitLab 18 EE Ultimate |
| LLM | vLLM 部署的 MiniMax 大模型 |
| CLI | Claude CLI 对接 vLLM，已可正常使用 |

## 三、核心工作流

```
用户在 GitLab Issue 中 @bot  ──webhook──►  服务接收事件
                                              │
                                              ▼
                                         解析指令/参数
                                         (延迟? 优先级?)
                                              │
                                              ▼
                                         入队 / 调度
                                              │
                                              ▼
                                        Worker 执行:
                                         ├─ clone/pull 仓库
                                         ├─ 创建分支 (首次)
                                         ├─ 调用 claude cli 实现需求
                                         ├─ commit & push
                                         ├─ 创建 MR 关联 issue (首次)
                                         └─ 回复 issue 评论(结果/MR链接)
                                              │
                                              ▼
                                  用户在 issue 继续 @bot 追加修改
                                         (循环上述流程)
```

## 四、技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI |
| 前端 | Vue 3 + Vite + Naive UI (或 Element Plus) |
| 调度 | 自研：asyncio + 数据库队列 |
| 任务隔离 | Docker 容器 (每个任务独立容器，完整 OS 级隔离) |
| 数据库 | SQLite (aiosqlite) |
| ORM | SQLAlchemy 2.0 (async) |
| Git 操作 | 容器内 git 命令 |
| GitLab API | python-gitlab (宿主机调度器调用) |
| Claude CLI | 容器内调用 |

## 五、系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                        GitLab 18 EE                          │
│  ┌──────────┐   ┌────────────────┐   ┌──────────────┐       │
│  │  Issue    │   │  Webhook 配置   │   │  MR / Branch │       │
│  │  @bot ... │──►│  Note Events   │   │              │       │
│  └──────────┘   └───────┬────────┘   └──────▲───────┘       │
└─────────────────────────┼───────────────────┼────────────────┘
                          │ HTTP POST         │ GitLab API
                          ▼                   │
┌─────────────────────────────────────────────┼────────────────┐
│             Host: Bot Service (FastAPI)      │                │
│                                             │                │
│  ┌──────────────┐   ┌──────────────────┐    │                │
│  │   Webhook    │──►│   Task Manager   │    │                │
│  │   Handler    │   │   (解析/入队)     │    │                │
│  └──────────────┘   └───────┬──────────┘    │                │
│                             │               │                │
│  ┌──────────────┐   ┌──────▼──────────┐     │                │
│  │  Web Admin   │   │   Scheduler     │     │                │
│  │  (Vue 3 SPA) │   │  ┌───────────┐  │     │                │
│  │              │◄──│  │  Queue     │  │     │                │
│  │ - 任务列表   │   │  │  Engine    │  │     │                │
│  │ - 日志查看   │   │  └─────┬─────┘  │     │                │
│  │ - 配置管理   │   │        │        │     │                │
│  │ - 负载监控   │   │  ┌─────▼─────┐  │     │                │
│  └──────────────┘   │  │  Worker   │  │     │                │
│                     │  │  Manager  │  │     │                │
│         ┌───────────┤  └─────┬─────┘  │     │                │
│         │  SQLite   │        │docker  │     │                │
│         │  (tasks,  │        │run     │     │                │
│         │   logs,   │        │        │     │                │
│         │   config) │        ▼        │     │                │
│         └───────────┘                 │     │                │
│  ┌────────────────────────────────────┼─────┼──────────────┐ │
│  │          Docker Containers         │     │              │ │
│  │                                    │     │              │ │
│  │  ┌──────────────────┐  ┌──────────────────┐             │ │
│  │  │ Container Task-A │  │ Container Task-B │  ...        │ │
│  │  │                  │  │                  │             │ │
│  │  │ - 独立网络空间   │  │ - 独立网络空间    │             │ │
│  │  │ - 独立文件系统   │  │ - 独立文件系统    │             │ │
│  │  │ - CPU/内存限制   │  │ - CPU/内存限制    │             │ │
│  │  │                  │  │                  │             │ │
│  │  │ git clone/branch │  │ git clone/branch │             │ │
│  │  │ claude -p "..."  │  │ claude -p "..."  │             │ │
│  │  │ mvn compile/test │  │ mvn compile/test │             │ │
│  │  │ git push ────────┼──┼──────────────────┼─────────┘   │ │
│  │  └──────┬───────────┘  └──────┬───────────┘             │ │
│  │         │ volume mount        │ volume mount             │ │
│  │         ▼                     ▼                         │ │
│  │  ┌─────────────────────────────────────────────────┐    │ │
│  │  │  /data/repos/{project}/.bare       (只读挂载)   │    │ │
│  │  │  /data/shared/.m2/repository       (只读挂载)   │    │ │
│  │  │  /data/config/claude               (只读挂载)   │    │ │
│  │  └─────────────────────────────────────────────────┘    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                              │                               │
│                              ▼                               │
│                        vLLM Server                           │
│                       (MiniMax LLM)                          │
└──────────────────────────────────────────────────────────────┘
```

### 5.1 任务隔离策略 (Docker)

每个任务在独立的 Docker 容器中执行，实现完整的 OS 级隔离：

| 隔离维度 | 效果 |
|---|---|
| 文件系统 | 独立 overlay fs，容器销毁即回收 |
| 网络/端口 | 独立网络命名空间，多任务可同时监听 8080 |
| 进程空间 | 独立 PID 命名空间，kill 不会误杀 |
| 环境变量 | 天然隔离，不同任务可用不同 JAVA_HOME 等 |
| CPU/内存 | cgroups 限制，单任务 OOM 不影响全局 |
| 临时文件 | 独立 /tmp，无锁文件冲突 |
| 任务清理 | docker stop/rm 一条命令，进程树全部清理 |

磁盘优化 — 共享只读数据，避免重复占用：

```
/data/
├── repos/                        # 裸仓库 (每个项目一份, 所有任务共享)
│   └── {project_id}/.bare/
├── shared/
│   └── .m2/repository/           # 公共 Maven 依赖 (所有任务共享)
└── config/
    └── claude/                   # Claude CLI 配置 (共享)
```

## 六、功能分解

### 6.1 GitLab 事件监听

- 监听 Issue Note (评论) Webhook
- 识别 `@bot` 提及
- 解析附加参数（延迟时间、优先级等）
- 支持的指令类型：
  - 首次触发：根据 issue 描述实现需求
  - 追加修改：在已有分支上继续修改
  - 取消/停止：终止正在执行的任务

### 6.2 任务调度引擎

- 任务队列（FIFO，支持优先级）
- 延迟/定时执行
- 并发控制（可配置最大并行数）
- 动态并发：根据 vLLM 服务器负载动态调整
- 任务状态管理：pending → queued → running → success/failed/cancelled
- 任务超时处理
- 失败重试策略（可选）

### 6.3 Worker 执行器 (Docker 容器)

- 每个任务启动一个独立的 Docker 容器执行
- 容器内完成：git clone/branch、调用 Claude CLI、编译测试、commit & push
- 宿主机 Scheduler 负责：创建 MR（通过 GitLab API）、回写 issue 评论
- 支持在已有分支上追加 commit（追加修改场景）
- 任务取消 = `docker stop`，干净终止整个进程树

### 6.4 管理后台 (Web Dashboard)

- 任务列表（状态、进度、关联 issue）
- 手动操作：立即执行、停止、重试、删除
- 调度配置：并发数、延迟策略
- vLLM 服务器负载监控
- 执行日志查看
- 系统配置管理

## 七、核心模块详细设计

### 7.1 Webhook Handler

```
POST /api/webhook/gitlab
```

- 接收 GitLab Note Hook (评论事件)
- 校验 Secret Token
- 只处理包含 `@bot` 的评论
- 解析指令语法，例如：

```
@ai-bot 请实现这个功能                    # 基本触发
@ai-bot delay=30m 30分钟后开始执行          # 延迟执行
@ai-bot priority=high 紧急需求             # 优先级
@ai-bot cancel                            # 取消当前任务
@ai-bot status                            # 查询任务状态
```

### 7.2 Task Manager

数据模型（核心表）：

```sql
-- 任务表
CREATE TABLE tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    gitlab_project_id   INTEGER NOT NULL,
    gitlab_issue_iid    INTEGER NOT NULL,
    gitlab_note_id      INTEGER,
    trigger_user        TEXT NOT NULL,
    instruction         TEXT NOT NULL,      -- 用户指令内容
    task_type           TEXT NOT NULL,      -- new_task / follow_up / cancel
    status              TEXT NOT NULL DEFAULT 'pending',
                                           -- pending/queued/scheduled/running/
                                           -- success/failed/cancelled/timeout
    priority            INTEGER DEFAULT 0,  -- 优先级，数字越大越优先
    scheduled_at        DATETIME,           -- 计划执行时间 (延迟执行)
    started_at          DATETIME,
    finished_at         DATETIME,
    branch_name         TEXT,               -- 关联的 git 分支
    mr_iid              INTEGER,            -- 关联的 MR iid
    container_name      TEXT,               -- Docker 容器名（用于 stop/logs，格式: glmr-{task_id}-p{project_id}-i{issue_iid}）
    container_id        TEXT,               -- Docker 容器 ID（docker run 返回的完整 ID）
    error_message       TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 任务日志表
CREATE TABLE task_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL REFERENCES tasks(id),
    level           TEXT NOT NULL DEFAULT 'info',  -- info/warn/error
    message         TEXT NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 系统配置表
CREATE TABLE system_config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT
);
```

### 7.3 Scheduler (自研调度器)

核心逻辑（单进程 asyncio 循环）：

```
每 N 秒轮询一次:
  1. 检查 scheduled tasks → 到时间的移入 queued
  2. 查询当前 running 任务数
  3. 查询 vLLM 负载 (可选: GET vllm/v1/models 或自定义监控端点)
  4. 计算可并发槽位 = min(max_concurrency, 动态上限) - running_count
  5. 从 queued 中按优先级取 N 个任务
  6. 为每个任务启动 Docker 容器 (docker run)
  7. 检查超时任务 → 标记 timeout 并 docker stop 容器
```

动态并发控制策略：
- 设定 vLLM GPU 利用率阈值（如 80%）
- 高于阈值 → 不启动新任务
- 低于阈值 → 按空闲比例放行

### 7.4 Worker 执行器 (Docker 容器)

#### 7.4.1 基础镜像

构建包含所有工具的基础镜像，离线环境提前 build 好：

```dockerfile
FROM ubuntu:22.04

# 基础工具
RUN apt-get update && apt-get install -y \
    git curl wget unzip jq

# 多版本 JDK (按需)
RUN apt-get install -y openjdk-17-jdk openjdk-21-jdk
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

# Maven / Gradle
COPY apache-maven-3.9.x /opt/maven
ENV PATH="/opt/maven/bin:$PATH"

# Node.js (如果有前端项目)
COPY node-v20.x /opt/node
ENV PATH="/opt/node/bin:$PATH"

# Claude CLI
COPY claude /usr/local/bin/claude
COPY claude-config /root/.claude/

# 工作入口
WORKDIR /workspace
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

#### 7.4.2 容器内执行脚本 (entrypoint.sh)

```bash
#!/bin/bash
set -e

# 1. 从本地裸仓库 clone (快速, 不走网络)
git clone /repos/bare /workspace/repo
cd /workspace/repo
git remote set-url origin "$GITLAB_URL/$PROJECT_PATH.git"

# 2. 分支管理
if [ "$TASK_TYPE" = "new_task" ]; then
    git checkout -b "$TASK_BRANCH" origin/main
else
    git fetch origin "$TASK_BRANCH"
    git checkout "$TASK_BRANCH"
    git pull origin "$TASK_BRANCH"
fi

# 3. 复制共享 .m2 为可写层 (避免只读挂载问题)
if [ -d /shared/.m2/repository ]; then
    cp -al /shared/.m2/repository /root/.m2-local/repository 2>/dev/null || true
    export MAVEN_OPTS="-Dmaven.repo.local=/root/.m2-local/repository"
fi

# 4. 调用 Claude CLI
claude -p "$(cat /task/prompt.txt)" --output-format json > /task/result.json 2>&1

# 5. 提交 & 推送
git add -A
if git diff --cached --quiet; then
    echo '{"status":"no_changes"}' > /task/result.json
else
    git commit -m "bot: implement issue #${ISSUE_IID} - ${COMMIT_MSG}"
    git push origin "$TASK_BRANCH"
    echo '{"status":"success"}' > /task/result.json
fi
```

#### 7.4.3 容器命名规范

所有 Worker 容器使用统一前缀 `glmr-`（gitlab-mr 缩写），便于识别和批量操作：

```
格式:  glmr-{task_id}-p{project_id}-i{issue_iid}
示例:  glmr-42-p17-i123
```

- `glmr-` 前缀：标识属于本系统的容器，与其他容器区分
- `{task_id}`：任务 ID，唯一标识
- `p{project_id}`：GitLab 项目 ID
- `i{issue_iid}`：Issue 编号

常用运维命令：

```bash
# 查看所有 bot 容器
docker ps --filter "name=glmr-"

# 批量停止所有 bot 容器 (紧急情况)
docker stop $(docker ps -q --filter "name=glmr-")

# 清理所有已停止的 bot 容器 (如果没用 --rm)
docker rm $(docker ps -aq --filter "name=glmr-" --filter "status=exited")

# 查看某个项目的所有容器
docker ps --filter "name=glmr-.*-p17"

# 查看某个 issue 的容器
docker ps --filter "name=glmr-.*-i123"
```

#### 7.4.4 宿主机 Worker Manager

```python
# 容器命名前缀
CONTAINER_PREFIX = "glmr"

async def execute_task(task):
    container_name = f"{CONTAINER_PREFIX}-{task.id}-p{task.gitlab_project_id}-i{task.gitlab_issue_iid}"
    branch = f"glmr/issue-{task.gitlab_issue_iid}"

    # 确保裸仓库存在并已 fetch 最新
    bare_repo = f"/data/repos/{task.gitlab_project_id}/.bare"
    if not exists(bare_repo):
        await run(f"git clone --bare {repo_url} {bare_repo}")
    await run(f"git -C {bare_repo} fetch origin")

    # 将 prompt 写入临时文件, 挂载进容器
    prompt = build_prompt(issue_title, issue_body, user_instruction)
    prompt_dir = f"/tmp/{container_name}"
    write_file(f"{prompt_dir}/prompt.txt", prompt)

    # 启动 Docker 容器
    docker_cmd = [
        "docker", "run",
        "--name", container_name,
        "--rm",                                        # 执行完自动清理

        # 资源限制
        "--cpus", "4",
        "--memory", "8g",

        # 网络: 需要访问 GitLab 和 vLLM
        "--network", "bot-network",

        # 挂载共享裸仓库 (只读, 加速 clone)
        "-v", f"{bare_repo}:/repos/bare:ro",

        # 挂载共享 Maven 仓库 (只读, 省去下载依赖)
        "-v", "/data/shared/.m2/repository:/shared/.m2/repository:ro",

        # 挂载 Claude CLI 配置 (只读)
        "-v", "/data/config/claude:/root/.claude:ro",

        # 挂载 prompt 和结果交换目录
        "-v", f"{prompt_dir}:/task",

        # 环境变量
        "-e", f"GITLAB_URL={gitlab_url}",
        "-e", f"PROJECT_PATH={project_path}",
        "-e", f"TASK_TYPE={task.task_type}",
        "-e", f"TASK_BRANCH={branch}",
        "-e", f"ISSUE_IID={task.gitlab_issue_iid}",
        "-e", f"COMMIT_MSG={short_description}",

        "bot-worker:latest"
    ]

    process = await asyncio.create_subprocess_exec(*docker_cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    # 获取容器 ID 并与 container_name 一起记录到任务表
    container_id = await get_container_id(container_name)
    await update_task(task.id,
        container_name=container_name,
        container_id=container_id)

    stdout, stderr = await asyncio.wait_for(
        process.communicate(), timeout=TASK_TIMEOUT)

    # 读取容器执行结果
    result = read_json(f"{prompt_dir}/result.json")

    # 宿主机负责 GitLab API 操作 (创建 MR、回复评论)
    if result["status"] == "success":
        if task.task_type == "new_task":
            mr = gitlab.create_mr(
                source=branch, target=default_branch,
                title=f"Resolve #{task.gitlab_issue_iid}: {issue_title}",
                description=f"Closes #{task.gitlab_issue_iid}")
            await update_task(task.id, mr_iid=mr.iid)

        gitlab.create_issue_note(task.gitlab_issue_iid,
            f"任务已完成\n分支: `{branch}`\nMR: !{mr.iid}")
```

#### 7.4.5 任务取消与清理

```python
async def cancel_task(task):
    # 一条命令, 进程树全部干掉, 容器自动清理 (--rm)
    await asyncio.create_subprocess_exec("docker", "stop", task.container_name)

async def cleanup_stale_containers():
    """服务启动时调用: 清理上次异常退出残留的容器"""
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-aq", "--filter", f"name={CONTAINER_PREFIX}-",
        stdout=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()
    if stdout.strip():
        await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", *stdout.decode().split())
```

### 7.5 Web Admin Dashboard

#### 7.5.1 认证：GitLab OIDC 集成

Dashboard 通过 GitLab 18 EE 的 OIDC Provider 实现单点登录，用户无需单独注册账号：

```
用户访问 Dashboard  →  跳转 GitLab 授权  →  回调获取 ID Token  →  解析用户身份/角色
```

**GitLab 侧配置 (Admin → Applications)：**

```
Name:           GLMR Bot Dashboard
Redirect URI:   https://bot.internal.com/api/auth/callback
Scopes:         openid profile email read_user
Confidential:   Yes
```

**认证流程 (Authorization Code Flow)：**

```
┌──────────┐     1. 访问 /dashboard     ┌───────────┐
│  Browser  │ ──────────────────────────► │  FastAPI   │
│           │ ◄─── 2. 302 → GitLab ───── │  Backend   │
│           │                             └───────────┘
│           │     3. 跳转 GitLab 登录
│           │ ──────────────────────────► ┌───────────┐
│           │ ◄─── 4. 用户授权 ────────── │  GitLab   │
│           │                             │  OIDC     │
│           │     5. 回调 /auth/callback  └───────────┘
│           │        携带 code
│           │ ──────────────────────────► ┌───────────┐
│           │                             │  FastAPI   │
│           │                             │  用 code   │
│           │                             │  换 token  │
│           │ ◄─── 6. Set-Cookie ──────── │  解析身份  │
│           │        (JWT session)        └───────────┘
└──────────┘
```

**从 ID Token 中提取的用户信息：**

```json
{
  "sub": "12345",
  "name": "张三",
  "preferred_username": "zhangsan",
  "email": "zhangsan@company.com",
  "groups": ["devops", "backend-team"]
}
```

#### 7.5.2 角色与权限模型

角色通过 `system_config` 中配置的管理员列表 + GitLab 用户身份自动判定：

| 角色 | 判定规则 | 权限 |
|---|---|---|
| **admin** | `username` 在管理员列表中，或属于指定 GitLab 组 | 查看/管理所有任务，系统配置，用户管理 |
| **user** | 通过 OIDC 登录的普通用户 | 仅查看/管理自己触发的任务 |

权限矩阵：

| 操作 | user | admin |
|---|---|---|
| 查看自己的任务列表 | O | O |
| 查看自己的任务详情/日志 | O | O |
| 取消/重试自己的任务 | O | O |
| 查看所有用户的任务 | X | O |
| 取消/重试他人的任务 | X | O |
| 立即执行任务 (跳过延迟) | X | O |
| 系统配置管理 | X | O |
| 查看系统监控 (vLLM 负载) | O (只读) | O |
| 用户/管理员管理 | X | O |

数据模型新增 — 用户表：

```sql
-- 用户表 (OIDC 登录后自动创建)
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    gitlab_user_id  INTEGER NOT NULL UNIQUE,  -- GitLab 用户 ID (OIDC sub)
    username        TEXT NOT NULL UNIQUE,      -- GitLab 用户名
    display_name    TEXT,                      -- 显示名称
    email           TEXT,
    avatar_url      TEXT,
    role            TEXT NOT NULL DEFAULT 'user',  -- user / admin
    last_login_at   DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

管理员列表配置（`system_config` 表）：

```
key:   admin_usernames
value: ["zhangsan", "lisi", "admin"]

key:   admin_gitlab_groups
value: ["devops", "platform-team"]
```

#### 7.5.3 页面规划

| 页面 | user 可见 | admin 可见 | 功能 |
|---|---|---|---|
| 我的任务 | O | O | 当前用户触发的任务列表，按状态筛选，实时刷新 |
| 全部任务 | X | O | 所有用户的任务列表，支持按用户/项目/状态筛选 |
| 任务详情 | O (仅自己) | O (全部) | 查看完整日志、Claude CLI 输出、git diff |
| 系统监控 | O (只读) | O | vLLM 负载、队列深度、Worker 容器状态 |
| 统计分析 | X | O | 用户排行、趋势对比、用户明细、项目维度、状态分布、导出 CSV |
| 配置管理 | X | O | Bot 名称、并发数、超时、GitLab Token、管理员列表 |
| 项目管理 | X | O | 管理哪些 GitLab 项目启用了 bot |

#### 7.5.4 页面布局详细设计

##### 整体框架 (Layout)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Header                                                              │
│  ┌─────────┐                              ┌────────────────────────┐ │
│  │ GLMR图标 │  GitLab Issue → MR Bot      │ [张三] ▼  [退出登录]  │ │
│  └─────────┘                              └────────────────────────┘ │
├────────────┬─────────────────────────────────────────────────────────┤
│  Sidebar   │  Content Area                                           │
│            │                                                         │
│  我的任务  │   (各页面内容)                                           │
│  全部任务* │                                                         │
│  ───────── │                                                         │
│  系统监控  │                                                         │
│  统计分析* │                                                         │
│  ───────── │                                                         │
│  项目管理* │                                                         │
│  配置管理* │                                                         │
│  用户管理* │                                                         │
│            │                                                         │
│            │                                                         │
│  ───────── │                                                         │
│  v0.1.0    │                                                         │
│  * admin   │                                                         │
├────────────┴─────────────────────────────────────────────────────────┤
│  Footer: GLMR Bot v0.1.0 | 队列: 3 等待 / 2 运行中                   │
└──────────────────────────────────────────────────────────────────────┘
```

- Header 右侧显示用户头像 + 用户名下拉菜单 (个人信息/退出)
- Sidebar 带 `*` 标记的菜单仅 admin 可见
- Footer 始终显示队列摘要信息，方便快速掌握系统状态

##### 登录页 (Login.vue)

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│                                                                      │
│                    ┌────────────────────────────┐                    │
│                    │                            │                    │
│                    │      GLMR Bot 图标         │                    │
│                    │                            │                    │
│                    │   GitLab Issue → MR Bot     │                    │
│                    │                            │                    │
│                    │  ┌──────────────────────┐  │                    │
│                    │  │                      │  │                    │
│                    │  │  使用 GitLab 账号登录  │  │                    │
│                    │  │                      │  │                    │
│                    │  └──────────────────────┘  │                    │
│                    │                            │                    │
│                    │   点击后跳转 GitLab 授权    │                    │
│                    │                            │                    │
│                    └────────────────────────────┘                    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

- 居中卡片，单一按钮，点击后 `window.location = /api/auth/login`
- 回调成功后自动跳转到"我的任务"页面

##### 我的任务 (MyTasks.vue) — user + admin 均可见

```
┌─────────────────────────────────────────────────────────────────────┐
│  我的任务                                                            │
│                                                                      │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ 统计卡片行                                            │            │
│  │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │            │
│  │ │ 总计  12 │ │ 运行中 2 │ │ 等待中 3 │ │ 已完成 7 │ │            │
│  │ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │            │
│  └──────────────────────────────────────────────────────┘            │
│                                                                      │
│  筛选条件:                                                           │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ 状态 ▼   │ │ 项目 ▼       │ │ 时间范围 ▼   │ │ 搜索关键词...  │  │
│  └──────────┘ └──────────────┘ └──────────────┘ └────────────────┘  │
│                                                                      │
│  ┌───┬──────┬────────┬──────────────┬────────┬────────┬──────────┐  │
│  │ # │ 状态 │ 项目    │ Issue        │ 类型   │ 创建时间 │ 操作    │  │
│  ├───┼──────┼────────┼──────────────┼────────┼────────┼──────────┤  │
│  │42 │ ● 运 │ myapp  │ #123 用户登录 │ 新建   │ 10:30  │ [详情]  │  │
│  │   │  行中│        │              │        │        │ [取消]  │  │
│  ├───┼──────┼────────┼──────────────┼────────┼────────┼──────────┤  │
│  │41 │ ● 等 │ myapp  │ #120 修复BUG  │ 新建   │ 10:15  │ [详情]  │  │
│  │   │  待中│        │              │        │        │ [取消]  │  │
│  ├───┼──────┼────────┼──────────────┼────────┼────────┼──────────┤  │
│  │38 │ ✓ 成 │ api-gw │ #89 添加限流  │ 追加   │ 09:00  │ [详情]  │  │
│  │   │  功  │        │  MR !45      │        │        │ [重试]  │  │
│  ├───┼──────┼────────┼──────────────┼────────┼────────┼──────────┤  │
│  │35 │ ✗ 失 │ myapp  │ #115 重构服务 │ 新建   │ 昨天   │ [详情]  │  │
│  │   │  败  │        │              │        │ 16:20  │ [重试]  │  │
│  └───┴──────┴────────┴──────────────┴────────┴────────┴──────────┘  │
│                                                                      │
│  ◄ 1 2 3 ... ►                                           每页 20 ▼  │
└─────────────────────────────────────────────────────────────────────┘
```

- 状态列使用彩色圆点: 绿=成功, 蓝=运行中, 黄=等待, 红=失败, 灰=已取消
- Issue 列显示 `#iid 标题`，可点击跳转 GitLab Issue 页面
- 成功的任务显示关联的 MR `!iid`，可点击跳转
- 操作列: 运行中/等待中 → [详情][取消]; 成功/失败 → [详情][重试]
- 表格支持按列排序
- 10s 自动轮询刷新 (或 WebSocket 推送)

##### 全部任务 (AllTasks.vue) — admin only

```
┌─────────────────────────────────────────────────────────────────────┐
│  全部任务 (管理员)                                                    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────┐            │
│  │ 统计卡片行 (全局)                                      │            │
│  │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │            │
│  │ │ 总计 128 │ │ 运行中 4 │ │ 等待中 8 │ │ 今日完成25│ │            │
│  │ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │            │
│  └──────────────────────────────────────────────────────┘            │
│                                                                      │
│  筛选条件:                                                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌─────────┐ ┌────────┐ │
│  │ 状态 ▼   │ │ 用户 ▼   │ │ 项目 ▼       │ │ 时间 ▼  │ │ 搜索.. │ │
│  └──────────┘ └──────────┘ └──────────────┘ └─────────┘ └────────┘ │
│                                                                      │
│  ┌───┬──────┬────────┬────────┬──────────────┬──────┬──────┬─────┐  │
│  │ # │ 状态 │ 用户   │ 项目    │ Issue        │ 类型 │ 时间 │ 操作│  │
│  ├───┼──────┼────────┼────────┼──────────────┼──────┼──────┼─────┤  │
│  │42 │ ● 运 │ 张三   │ myapp  │ #123 用户登录 │ 新建 │10:30 │[详]│  │
│  │   │  行中│        │        │              │      │      │[停]│  │
│  ├───┼──────┼────────┼────────┼──────────────┼──────┼──────┼─────┤  │
│  │41 │ ● 定 │ 李四   │ api-gw │ #90 添加缓存  │ 新建 │10:15 │[详]│  │
│  │   │  时中│        │        │ delay=1h      │      │      │[即]│  │
│  │   │      │        │        │              │      │      │[停]│  │
│  ├───┼──────┼────────┼────────┼──────────────┼──────┼──────┼─────┤  │
│  │40 │ ✓ 成 │ 王五   │ myapp  │ #119 修复NPE  │ 追加 │09:45 │[详]│  │
│  │   │  功  │        │        │  MR !44      │      │      │[试]│  │
│  └───┴──────┴────────┴────────┴──────────────┴──────┴──────┴─────┘  │
│                                                                      │
│  [批量操作 ▼: 取消选中 / 重试选中]              ◄ 1 2 3 ... ►        │
└─────────────────────────────────────────────────────────────────────┘
```

- 相比"我的任务"多了**用户列**和**批量操作**
- [即] = 立即执行(跳过延迟)，仅对"定时中"状态显示
- 支持 checkbox 多选后批量取消/重试

##### 任务详情 (TaskDetail.vue)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ◄ 返回列表    任务 #42                              ● 运行中       │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 基本信息                                                        │ │
│  │ ┌──────────────────────────┬──────────────────────────────────┐ │ │
│  │ │ 项目     myapp           │ 触发用户   张三                   │ │ │
│  │ │ Issue    #123 实现用户登录 → │ 类型      新建任务              │ │ │
│  │ │ 分支     glmr/issue-123  │ 容器      glmr-42-p17-i123      │ │ │
│  │ │ MR       !46 (Draft) →   │ 优先级    普通                   │ │ │
│  │ │ 创建时间  2026-03-08 10:30│ 开始时间  2026-03-08 10:31      │ │ │
│  │ └──────────────────────────┴──────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 用户指令                                                        │ │
│  │ ┌─────────────────────────────────────────────────────────────┐ │ │
│  │ │ @ai-bot 请实现用户登录功能，要求：                              │ │ │
│  │ │ 1. 支持用户名密码登录                                         │ │ │
│  │ │ 2. 支持手机号验证码登录                                       │ │ │
│  │ │ 3. 登录后签发 JWT Token                                      │ │ │
│  │ └─────────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  [执行日志]    [Claude 输出]    [Git Diff]                    │    │
│  ├──────────────────────────────────────────────────────────────┤    │
│  │                                                              │    │
│  │  Tab 1: 执行日志                                             │    │
│  │  ┌──────────────────────────────────────────────────────┐    │    │
│  │  │ 10:31:01 [INFO]  启动容器 glmr-42-p17-i123          │    │    │
│  │  │ 10:31:02 [INFO]  git clone 完成 (1.2s)               │    │    │
│  │  │ 10:31:02 [INFO]  创建分支 glmr/issue-123             │    │    │
│  │  │ 10:31:03 [INFO]  开始调用 Claude CLI...               │    │    │
│  │  │ 10:32:45 [INFO]  Claude CLI 执行完成 (102s)           │    │    │
│  │  │ 10:32:46 [INFO]  git add -A (5 files changed)        │    │    │
│  │  │ 10:32:46 [INFO]  git commit: bot: implement #123     │    │    │
│  │  │ 10:32:48 [INFO]  git push origin glmr/issue-123      │    │    │
│  │  │ 10:32:49 [INFO]  创建 MR !46                         │    │    │
│  │  │ 10:32:50 [INFO]  任务完成                             │    │    │
│  │  │                                                      │    │    │
│  │  │                                           [自动滚动 ✓]│    │    │
│  │  └──────────────────────────────────────────────────────┘    │    │
│  │                                                              │    │
│  │  Tab 2: Claude 输出 (折叠的 JSON/文本)                       │    │
│  │  Tab 3: Git Diff (语法高亮, 文件树 + diff 预览)              │    │
│  │                                                              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  操作栏:                                                             │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ [取消任务]  [重试任务]  [立即执行*]    [在 GitLab 中查看 Issue →]│    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

- 顶部面包屑 + 状态 badge
- 基本信息区：两列 key-value，Issue/MR 可点击跳转 GitLab
- 用户指令区：灰底展示原始 @bot 评论内容
- Tab 区域：
  - **执行日志**：实时流式显示（运行中时自动滚动到底部）
  - **Claude 输出**：Claude CLI 的 JSON 输出，可展开/折叠
  - **Git Diff**：左侧文件树 + 右侧 diff 预览，语法高亮
- 底部操作栏：按当前状态和角色动态显示按钮

##### 系统监控 (Monitor.vue)

```
┌─────────────────────────────────────────────────────────────────────┐
│  系统监控                                                  [手动刷新]│
│                                                                      │
│  ┌───────────────────────────────┬─────────────────────────────────┐ │
│  │ vLLM 服务状态                  │ 任务队列                        │ │
│  │                               │                                 │ │
│  │ 端点: http://10.0.1.5:8000   │ ┌───────┐ ┌──────┐ ┌────────┐  │ │
│  │ 状态: ● 在线                  │ │等待  8 │ │运行 4│ │定时  2 │  │ │
│  │ 模型: MiniMax-xxx             │ └───────┘ └──────┘ └────────┘  │ │
│  │                               │                                 │ │
│  │ GPU 利用率:                   │ 并发: 4 / 6 (上限)              │ │
│  │ ████████████████░░░░  78%     │                                 │ │
│  │                               │ 今日统计:                       │ │
│  │ 显存使用:                     │ 完成: 25  失败: 3  取消: 1      │ │
│  │ ██████████████░░░░░░  65%     │                                 │ │
│  │                               │ 平均执行时间: 3m 22s            │ │
│  │ 请求队列: 2 pending           │                                 │ │
│  └───────────────────────────────┴─────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 运行中的容器                                          admin only │ │
│  │ ┌──────────────────────┬──────┬────────┬──────┬───────┬──────┐ │ │
│  │ │ 容器名               │ 用户 │ Issue  │ CPU  │ 内存  │ 运行 │ │ │
│  │ ├──────────────────────┼──────┼────────┼──────┼───────┼──────┤ │ │
│  │ │ glmr-42-p17-i123     │ 张三 │ #123   │ 2.3c │ 1.8G  │ 3m   │ │ │
│  │ │ glmr-43-p17-i124     │ 张三 │ #124   │ 1.1c │ 0.9G  │ 1m   │ │ │
│  │ │ glmr-44-p22-i56      │ 李四 │ #56    │ 3.8c │ 4.2G  │ 8m   │ │ │
│  │ │ glmr-45-p22-i57      │ 王五 │ #57    │ 0.5c │ 0.3G  │ 30s  │ │ │
│  │ └──────────────────────┴──────┴────────┴──────┴───────┴──────┘ │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 任务趋势 (最近 7 天)                                            │ │
│  │                                                                 │ │
│  │  30 ┤                                                           │ │
│  │     │          ██                                               │ │
│  │  20 ┤    ██    ██    ██                                         │ │
│  │     │    ██    ██    ██    ██                                    │ │
│  │  10 ┤    ██    ██    ██    ██    ██    ██                        │ │
│  │     │    ██    ██    ██    ██    ██    ██    ██                  │ │
│  │   0 ┼────┴─────┴─────┴─────┴─────┴─────┴─────┴──               │ │
│  │      Mon  Tue   Wed   Thu   Fri   Sat   Sun                     │ │
│  │                                                                 │ │
│  │  ■ 成功  ■ 失败  ■ 取消                                        │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

- 顶部左右分栏：vLLM 状态 + 任务队列概览
- vLLM 区域：连接状态、GPU 利用率进度条、显存用量（数据来自 vLLM metrics 端点）
- 队列区域：当前等待/运行/定时数量，当日统计
- 容器列表（admin）：实时显示 docker stats 数据（CPU/内存/运行时长）
- 底部趋势图：最近 7 天任务完成/失败/取消的柱状图
- 整个页面 15s 自动刷新

##### 配置管理 (Settings.vue) — admin only

```
┌─────────────────────────────────────────────────────────────────────┐
│  系统配置                                                  [保存配置]│
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 基础配置                                                        │ │
│  │                                                                 │ │
│  │ Bot 触发词          [@ai-bot          ]                         │ │
│  │ 默认分支            [main             ]                         │ │
│  │ 分支命名模板        [glmr/issue-{iid} ]                         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 调度配置                                                        │ │
│  │                                                                 │ │
│  │ 最大并发数          [6    ] (同时运行的容器数)                    │ │
│  │ 任务超时(分钟)      [30   ] (单个任务最大执行时间)                │ │
│  │ 调度间隔(秒)        [5    ] (轮询队列间隔)                       │ │
│  │ 动态并发            [● 启用] (根据 vLLM 负载自动调整)            │ │
│  │ GPU利用率阈值(%)    [80   ] (高于此值暂停调度)                    │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 容器资源限制                                                     │ │
│  │                                                                 │ │
│  │ CPU 限制(核)        [4    ]                                     │ │
│  │ 内存限制            [8g   ]                                     │ │
│  │ Docker 网络         [bot-network      ]                         │ │
│  │ Worker 镜像         [bot-worker:latest]                         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 连接配置                                                        │ │
│  │                                                                 │ │
│  │ GitLab URL          [https://gitlab.internal.com    ]           │ │
│  │ GitLab Bot Token    [glpat-*******************      ] [测试连接]│ │
│  │ Webhook Secret      [********************************]          │ │
│  │ vLLM 端点           [http://10.0.1.5:8000           ] [测试连接]│ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 权限配置                                                        │ │
│  │                                                                 │ │
│  │ 管理员用户名        [zhangsan, lisi, admin           ]          │ │
│  │ 管理员 GitLab 组    [devops, platform-team            ]          │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

- 按类别分卡片：基础/调度/容器/连接/权限
- Token 类字段默认遮盖，点击可查看
- [测试连接] 按钮可在线验证 GitLab/vLLM 连通性
- 修改后点击 [保存配置] 统一提交，实时生效

##### 用户管理 (Users.vue) — admin only

```
┌─────────────────────────────────────────────────────────────────────┐
│  用户管理                                                            │
│                                                                      │
│  ┌────────────────┐                                                  │
│  │ 搜索用户名...   │                                                  │
│  └────────────────┘                                                  │
│                                                                      │
│  ┌──────┬──────────┬──────────────────┬──────┬────────┬──────────┐  │
│  │ 头像 │ 用户名    │ 邮箱             │ 角色 │ 任务数 │ 最后登录 │  │
│  ├──────┼──────────┼──────────────────┼──────┼────────┼──────────┤  │
│  │ [头] │ zhangsan │ zhang@company.com│[admin▼]│   42 │ 今天10:30│  │
│  ├──────┼──────────┼──────────────────┼──────┼────────┼──────────┤  │
│  │ [头] │ lisi     │ li@company.com   │[admin▼]│   28 │ 今天09:15│  │
│  ├──────┼──────────┼──────────────────┼──────┼────────┼──────────┤  │
│  │ [头] │ wangwu   │ wang@company.com │[user ▼]│   15 │ 昨天16:00│  │
│  ├──────┼──────────┼──────────────────┼──────┼────────┼──────────┤  │
│  │ [头] │ zhaoliu  │ zhao@company.com │[user ▼]│    3 │ 3天前    │  │
│  └──────┴──────────┴──────────────────┴──────┴────────┴──────────┘  │
│                                                                      │
│  用户通过 GitLab OIDC 首次登录后自动出现在此列表。                      │
│  角色修改即时生效，下次请求时应用新权限。                                │
└─────────────────────────────────────────────────────────────────────┘
```

- 角色列是 inline 下拉选择器，修改后直接调 `PUT /api/users/:id/role`
- 任务数列可点击跳转到"全部任务"页并自动筛选该用户
- 头像从 GitLab OIDC 的 avatar_url 获取

##### 统计分析 (Statistics.vue) — admin only

```
┌─────────────────────────────────────────────────────────────────────┐
│  统计分析                          时间范围: [最近7天 ▼]  [自定义...]│
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 全局概览                                                        │ │
│  │ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐  │ │
│  │ │ 总任务 156  │ │ 成功率 82% │ │ 平均耗时    │ │ 活跃用户 8   │  │ │
│  │ │ ↑12% vs 上周│ │ ↑3% vs上周 │ │ 3m 22s     │ │ ↑2 vs 上周   │  │ │
│  │ └────────────┘ └────────────┘ └────────────┘ └──────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────┬──────────────────────────────────┐ │
│  │ 用户排行 (任务数 Top 10)      │ 用户排行 (成功率)                │ │
│  │                              │                                  │ │
│  │ zhangsan  ████████████  42   │ lisi      ██████████████  95%    │ │
│  │ lisi      █████████     28   │ wangwu    ████████████    88%    │ │
│  │ wangwu    ██████        15   │ zhangsan  ██████████      83%    │ │
│  │ zhaoliu   ████          12   │ zhaoliu   █████████       80%    │ │
│  │ sunqi     ███            8   │ sunqi     ████████        75%    │ │
│  │                              │                                  │ │
│  └──────────────────────────────┴──────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 用户任务趋势 (最近 7 天)                                        │ │
│  │                                                                 │ │
│  │  20 ┤         ·                                                 │ │
│  │     │        / \        ·                                       │ │
│  │  15 ┤  ·    /   \      / \                                      │ │
│  │     │ / \  ·     \    /   ·                                     │ │
│  │  10 ┤/   \/   ----\--/   / \                                    │ │
│  │     │         ·    \/   /   \                                   │ │
│  │   5 ┤        / \       ·     ·                                  │ │
│  │     │                                                           │ │
│  │   0 ┼────┬─────┬─────┬─────┬─────┬─────┬─────                  │ │
│  │     Mon  Tue   Wed   Thu   Fri   Sat   Sun                      │ │
│  │                                                                 │ │
│  │  — zhangsan  --- lisi  ··· wangwu   [全选] [取消全选]           │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ 用户明细表                                                      │ │
│  │                                                                 │ │
│  │  ┌────────┬──────┬──────┬──────┬──────┬──────────┬───────────┐  │ │
│  │  │ 用户   │ 总数 │ 成功 │ 失败 │ 取消 │ 成功率   │ 平均耗时  │  │ │
│  │  ├────────┼──────┼──────┼──────┼──────┼──────────┼───────────┤  │ │
│  │  │zhangsan│  42  │  35  │   5  │   2  │   83.3%  │  3m 45s   │  │ │
│  │  │lisi    │  28  │  27  │   1  │   0  │   96.4%  │  2m 58s   │  │ │
│  │  │wangwu  │  15  │  13  │   1  │   1  │   86.7%  │  4m 12s   │  │ │
│  │  │zhaoliu │  12  │  10  │   2  │   0  │   83.3%  │  3m 30s   │  │ │
│  │  │sunqi   │   8  │   6  │   2  │   0  │   75.0%  │  5m 01s   │  │ │
│  │  ├────────┼──────┼──────┼──────┼──────┼──────────┼───────────┤  │ │
│  │  │ 合计   │ 105  │  91  │  11  │   3  │   86.7%  │  3m 22s   │  │ │
│  │  └────────┴──────┴──────┴──────┴──────┴──────────┴───────────┘  │ │
│  │                                                         [导出CSV]│ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────┬──────────────────────────────────┐ │
│  │ 项目维度统计                  │ 任务状态分布                      │ │
│  │                              │                                  │ │
│  │ myapp        ████████  48    │          ┌─────┐                 │ │
│  │ api-gateway  ██████    32    │       ┌──┤成功 │                 │ │
│  │ user-service ████      18    │  ┌────┤  │82%  │                 │ │
│  │ common-lib   ██         7    │  │失败├──┤     │                 │ │
│  │                              │  │10% │  └─────┘                 │ │
│  │                              │  └────┘  取消5%  超时3%          │ │
│  └──────────────────────────────┴──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

- **全局概览卡片**：总任务数、成功率、平均耗时、活跃用户数，均与上一周期对比显示趋势箭头
- **用户排行**：左侧按任务数排行，右侧按成功率排行，横向条形图直观对比
- **用户任务趋势**：折线图，每个用户一条线，可勾选/取消显示
- **用户明细表**：按用户汇总的详细数据表（总数/成功/失败/取消/成功率/平均耗时），底部有合计行，支持导出 CSV
- **项目维度统计**：按项目的任务数排行
- **任务状态分布**：饼图/环形图展示全局状态占比
- 顶部时间范围选择器：预设（今天/7天/30天/全部）+ 自定义日期范围，切换后所有图表联动刷新

#### 7.5.5 API 路由规划

```
# --- 认证 (无需登录) ---
GET    /api/auth/login               # 跳转 GitLab OIDC 授权
GET    /api/auth/callback            # OIDC 回调, 换取 token, 创建 session
POST   /api/auth/logout              # 注销
GET    /api/auth/me                  # 获取当前用户信息和角色

# --- Webhook (Token 校验, 无需 OIDC) ---
POST   /api/webhook/gitlab           # GitLab Webhook 入口

# --- 任务 (需登录) ---
GET    /api/tasks                    # 任务列表 (user: 仅自己, admin: 全部, ?user=xx 筛选)
GET    /api/tasks/:id                # 任务详情 (user: 仅自己, admin: 全部)
POST   /api/tasks/:id/cancel         # 取消任务 (user: 仅自己, admin: 全部)
POST   /api/tasks/:id/retry          # 重试任务 (user: 仅自己, admin: 全部)
POST   /api/tasks/:id/run-now        # 立即执行 (admin only)
GET    /api/tasks/:id/logs           # 任务日志 (user: 仅自己, admin: 全部)

# --- 监控 (需登录) ---
GET    /api/stats                    # 统计概览 (user: 自己的统计, admin: 全局统计)
GET    /api/monitor/vllm             # vLLM 负载 (全员可读)
GET    /api/monitor/containers       # 运行中的容器列表 (admin only)

# --- 统计分析 (admin only) ---
GET    /api/stats/overview           # 全局概览卡片 (总数/成功率/平均耗时/活跃用户, 含环比)
GET    /api/stats/by-user            # 用户维度明细 (每用户: 总/成功/失败/取消/成功率/平均耗时)
GET    /api/stats/by-project         # 项目维度统计 (每项目: 任务数)
GET    /api/stats/trend              # 趋势数据 (?group_by=user|project, 按天聚合)
GET    /api/stats/status-distribution # 任务状态分布 (饼图数据)
GET    /api/stats/export             # 导出 CSV (?dimension=user|project)
# 以上接口均支持 ?from=2026-03-01&to=2026-03-08 时间范围参数

# --- 管理 (admin only) ---
GET    /api/config                   # 系统配置
PUT    /api/config                   # 更新配置
GET    /api/users                    # 用户列表
PUT    /api/users/:id/role           # 修改用户角色
```

## 八、项目目录结构

```
gitlab_issues_to_mr/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口
│   │   ├── config.py               # 配置管理
│   │   ├── database.py             # SQLite/SQLAlchemy
│   │   ├── models.py               # 数据模型 (tasks, task_logs, users, system_config)
│   │   ├── api/
│   │   │   ├── auth.py             # OIDC 登录/回调/注销/me
│   │   │   ├── webhook.py          # Webhook handler
│   │   │   ├── tasks.py            # 任务管理 API (含权限过滤)
│   │   │   ├── users.py            # 用户管理 API (admin)
│   │   │   ├── config.py           # 配置 API (admin)
│   │   │   └── monitor.py          # 监控 API
│   │   ├── core/
│   │   │   ├── scheduler.py        # 调度器
│   │   │   ├── worker.py           # Worker 执行器 (Docker 容器管理)
│   │   │   ├── git_ops.py          # Git 操作封装
│   │   │   ├── gitlab_client.py    # GitLab API 封装
│   │   │   ├── claude_cli.py       # Claude CLI 封装
│   │   │   └── oidc.py             # OIDC 客户端 (token 交换/验证/用户信息)
│   │   ├── middleware/
│   │   │   └── auth.py             # 认证中间件 (session 校验, 角色注入)
│   │   └── utils/
│   │       ├── parser.py           # 指令解析
│   │       └── logger.py           # 日志工具
│   ├── requirements.txt
│   └── alembic/                    # 数据库迁移 (可选)
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── Login.vue           # 登录页 (跳转 GitLab OIDC)
│   │   │   ├── MyTasks.vue         # 我的任务 (user + admin)
│   │   │   ├── AllTasks.vue        # 全部任务 (admin only)
│   │   │   ├── TaskDetail.vue      # 任务详情
│   │   │   ├── Monitor.vue         # 系统监控
│   │   │   ├── Statistics.vue      # 统计分析 (admin only)
│   │   │   ├── Users.vue           # 用户管理 (admin only)
│   │   │   └── Settings.vue        # 配置管理 (admin only)
│   │   ├── components/
│   │   ├── composables/
│   │   │   └── useAuth.ts          # 认证状态管理 (用户信息/角色/登出)
│   │   ├── api/                    # API 封装
│   │   ├── router/
│   │   │   └── index.ts            # 路由守卫 (登录检查, 角色权限)
│   │   ├── stores/
│   │   │   └── user.ts             # 用户状态 (Pinia)
│   │   └── App.vue
│   ├── package.json
│   └── vite.config.ts
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── nginx.conf                  # 前端代理
├── DESIGN.md                       # 本设计文档
└── CLAUDE.md                       # Claude CLI 项目上下文
```

## 九、实现路线图

| 阶段 | 内容 | 交付物 |
|---|---|---|
| **P0 - 最小可用** | Webhook 接收 → 解析 @bot → Docker 容器内执行单个任务 → 创建分支/MR → 回复 issue | 能跑通完整流程的 MVP |
| **P1 - 队列调度** | 任务入队、调度器循环、并发控制、延迟执行、任务状态流转 | 可靠的异步任务系统 |
| **P2 - 管理后台** | Vue 3 Dashboard、任务列表/详情/日志、手动操作（取消/重试/立即执行）、配置管理 | 可视化管理界面 |
| **P3 - 认证与权限** | GitLab OIDC 集成、用户自动注册、角色权限 (user/admin)、任务归属与可见性隔离 | 多用户安全访问 |
| **P4 - 高级特性** | vLLM 负载监控、动态并发、追加修改(follow-up)、指令扩展、Docker Compose 一键部署 | 生产就绪 |

各阶段详细说明：

### P0 - 最小可用

目标：从 @bot 到 MR 的完整链路跑通。

- FastAPI 骨架 + SQLite 初始化
- Webhook handler 接收 GitLab Note Hook
- 解析 @bot 指令 (仅基本触发)
- Worker: 构建基础镜像、entrypoint.sh
- Worker: Docker 容器内 git clone → claude -p → commit → push
- 宿主机: 创建 MR、回复 issue 评论
- 单任务同步执行 (无队列, webhook 收到即执行)

### P1 - 队列调度

目标：支持多任务并发、延迟执行、可靠的状态管理。

- 任务入队 (webhook 不再同步执行, 写入 DB 后立即返回)
- Scheduler asyncio 循环 (轮询 + 调度)
- 并发控制 (可配置 max_concurrency)
- 延迟/定时执行 (scheduled_at)
- 任务状态流转完整实现
- 任务超时检测 + docker stop
- 容器命名规范 (glmr-{id}-p{pid}-i{iid})
- 服务启动时清理残留容器

### P2 - 管理后台

目标：可视化管理所有任务（暂无认证，后续 P3 补充）。

- Vue 3 + Vite + Naive UI 项目搭建
- 任务看板 (列表、状态筛选、实时刷新)
- 任务详情 (日志、Claude CLI 输出、git diff)
- 手动操作 (取消、重试、立即执行)
- 系统监控页 (队列深度、运行中容器)
- 配置管理页 (并发数、超时时间等)

### P3 - 认证与权限

目标：接入 GitLab OIDC，实现多用户隔离访问。

- GitLab OIDC 客户端 (Authorization Code Flow)
- 用户自动注册 (首次 OIDC 登录 → 写入 users 表)
- Session 管理 (JWT Cookie)
- 角色判定 (admin_usernames / admin_gitlab_groups)
- API 权限中间件 (user 只能操作自己的任务, admin 全部)
- 前端路由守卫 + 角色感知 UI (菜单/按钮动态显示)
- 用户管理页 (admin: 查看用户列表、修改角色)

### P4 - 高级特性

目标：生产环境打磨。

- vLLM 负载监控 + 动态并发调整
- 追加修改 (follow-up @bot, 在已有分支上继续)
- 指令扩展 (priority, cancel, status)
- Docker Compose 一键部署 (FastAPI + Nginx + SQLite 卷)
- 操作审计日志

## 十、配置方案 (已确定)

### 10.1 配置总览

所有配置通过 **环境变量** 注入（Docker 部署友好），并可在 Dashboard 配置管理页动态修改部分运行时参数。

#### 启动时环境变量（不可热更新，需重启服务）

```bash
# ===== GitLab 连接 =====
GITLAB_URL=https://gitlab.internal.com       # GitLab 实例地址
GITLAB_BOT_TOKEN=glpat-xxxxxxxxxxxx          # ai-bot 用户的 Personal Access Token
GITLAB_BOT_USERNAME=ai-bot                   # Bot 账号用户名 (可配置)
GITLAB_WEBHOOK_SECRET=your-webhook-secret    # Webhook 校验密钥

# ===== OIDC 认证 =====
OIDC_ISSUER_URL=https://gitlab.internal.com  # GitLab OIDC issuer (可配置)
OIDC_CLIENT_ID=glmr-bot-dashboard            # GitLab OAuth Application ID
OIDC_CLIENT_SECRET=xxxxxxxxxxxxxxxx          # GitLab OAuth Application Secret
OIDC_REDIRECT_URI=https://bot.internal.com/api/auth/callback

# ===== Claude CLI (透传到 Worker 容器) =====
ANTHROPIC_BASE_URL=http://10.0.1.5:8000/v1  # vLLM 端点
ANTHROPIC_API_KEY=your-vllm-api-key          # vLLM API Key
ANTHROPIC_MODEL=your-model-name              # 模型名称

# ===== vLLM 监控 =====
VLLM_METRICS_URL=http://10.0.1.5:8000/metrics  # vLLM Prometheus 端点

# ===== 服务自身 =====
DATABASE_URL=sqlite:///data/db/glmr.sqlite   # SQLite 数据库路径
SECRET_KEY=your-session-secret-key           # JWT Session 签名密钥
LOG_LEVEL=INFO
```

#### 运行时可配置项（Dashboard 配置管理页可热更新，存 system_config 表）

```yaml
# Bot 行为
bot_trigger_keyword: "@ai-bot"          # 触发词 (可配置)
branch_name_template: "glmr/issue-{iid}" # 分支命名模板

# 调度
max_concurrency: 6                       # 最大并发容器数
task_timeout_minutes: 30                 # 单任务超时 (默认30分钟, 可配置)
scheduler_interval_seconds: 5            # 调度轮询间隔
enable_dynamic_concurrency: true         # 是否启用动态并发
vllm_load_threshold_percent: 80          # vLLM 负载阈值

# 容器资源
container_cpus: "4"                      # 容器 CPU 限制
container_memory: "8g"                   # 容器内存限制
container_network: "bot-network"         # Docker 网络名
worker_image: "bot-worker:latest"        # Worker 镜像

# 权限
admin_usernames: ["zhangsan", "admin"]   # 管理员用户名列表 (可配置)
admin_gitlab_groups: ["devops"]          # 管理员 GitLab 组 (可配置)
```

### 10.2 各项确认详情

#### 1. Bot 账号方案

使用 GitLab 独立用户账号 `ai-bot`，名称通过 `GITLAB_BOT_USERNAME` 环境变量配置。

需在 GitLab 中预先创建该用户并生成 Personal Access Token，所需权限：

```
api, read_user, read_repository, write_repository
```

Bot 以此账号身份执行所有操作（push 代码、创建 MR、回复评论），Issue 中的回复将显示为 ai-bot 的头像和用户名。

#### 2. Claude CLI 对接 vLLM

通过环境变量对接，宿主机设置后透传到 Worker 容器：

```bash
# 宿主机 .env
ANTHROPIC_BASE_URL=http://10.0.1.5:8000/v1
ANTHROPIC_API_KEY=your-vllm-api-key
ANTHROPIC_MODEL=your-model-name

# docker run 时透传
docker run \
  -e ANTHROPIC_BASE_URL \
  -e ANTHROPIC_API_KEY \
  -e ANTHROPIC_MODEL \
  ...
```

#### 3. 触发词

默认 `@ai-bot`，通过 `bot_trigger_keyword` 运行时配置项可在 Dashboard 中修改。

Webhook handler 匹配逻辑：

```python
trigger = config.get("bot_trigger_keyword")  # "@ai-bot"
if trigger in note_body:
    # 提取 trigger 后面的指令内容
    instruction = note_body.split(trigger, 1)[1].strip()
```

#### 4. 工作目录

容器内固定使用 `/workspace/repo`，由 entrypoint.sh 管理。容器销毁即回收，无需额外清理。

#### 5. 超时策略

默认 30 分钟，通过 `task_timeout_minutes` 可在 Dashboard 中动态调整。

Scheduler 超时检测逻辑：

```python
if task.status == "running":
    elapsed = now - task.started_at
    if elapsed > timedelta(minutes=config.task_timeout_minutes):
        await docker_stop(task.container_name)
        task.status = "timeout"
```

#### 6. 分支命名规则

模板：`glmr/issue-{iid}`，通过 `branch_name_template` 可配置。

示例：

```
Issue #123 → 分支 glmr/issue-123
Issue #456 → 分支 glmr/issue-456
```

#### 7. 部署方式

Docker Compose 一键部署，包含三个服务：

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    env_file: .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # 控制 Worker 容器
      - glmr-data:/data                            # SQLite + 裸仓库
    ports:
      - "8080:8000"

  frontend:
    build: ./frontend
    depends_on:
      - backend

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - backend
      - frontend

volumes:
  glmr-data:

networks:
  default:
    name: bot-network      # Worker 容器也加入此网络
```

#### 8. vLLM 监控端点

vLLM 原生暴露 Prometheus 兼容的 `/metrics` 端点，无需额外配置。

关键指标（用于动态并发控制）：

```
vllm:num_requests_running    # 当前运行中的推理请求数 (Gauge)
vllm:num_requests_waiting    # 等待中的推理请求数 (Gauge)
vllm:gpu_cache_usage_perc    # GPU KV Cache 使用率 0~1 (Gauge)
```

Scheduler 动态并发判定逻辑：

```python
async def get_vllm_load():
    """解析 vLLM /metrics Prometheus 文本格式"""
    resp = await httpx.get(config.VLLM_METRICS_URL)
    metrics = parse_prometheus_text(resp.text)
    return {
        "requests_running": metrics["vllm:num_requests_running"],
        "requests_waiting": metrics["vllm:num_requests_waiting"],
        "gpu_cache_usage":  metrics["vllm:gpu_cache_usage_perc"],
    }

async def calculate_available_slots():
    load = await get_vllm_load()
    if load["gpu_cache_usage"] > config.vllm_load_threshold_percent / 100:
        return 0  # 负载过高, 暂停调度
    running = await count_running_tasks()
    return config.max_concurrency - running
```

Dashboard 监控页展示：
- `num_requests_running` / `num_requests_waiting` → 请求队列状态
- `gpu_cache_usage_perc` → GPU 缓存利用率进度条

如需更底层的 GPU 硬件指标（温度、功耗、显存），可额外部署 NVIDIA DCGM Exporter，但这不是必需的。

#### 9. OIDC 配置

GitLab 实例 URL 通过 `OIDC_ISSUER_URL` 环境变量配置。

OIDC Discovery 端点将自动拼接为：

```
{OIDC_ISSUER_URL}/.well-known/openid-configuration
```

#### 10. 管理员初始化

通过 `admin_usernames` 和 `admin_gitlab_groups` 配置项管理，可在环境变量中设置初始值，后续在 Dashboard 中动态修改。

首次部署时通过环境变量初始化：

```bash
INIT_ADMIN_USERNAMES=zhangsan,admin
INIT_ADMIN_GITLAB_GROUPS=devops
```

服务首次启动时写入 `system_config` 表，之后以数据库中的值为准。
