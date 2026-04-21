# Issue→Task→MR Refactoring Design

## Problem Statement

当前 Codify 的模型是 Task→MR（一个任务直接创建一个 MR）。需要重构为 Issue→Task→MR 三层模型：

- **Issue**：需求容器，组织和管理多个 Task
- **Task**：执行单元，一次 `claude -p` 调用
- **MR**：代码产出，一个 Issue 对应一个 MR

核心动机：利用 Claude Code CLI + 自建模型在非工作时段（如夜间）充分利用有限算力。需要支持任务预约调度、失败重试、session 复用（追加 prompt）等能力。

## Design Decisions

| 决策 | 选择 | 原因 |
|------|------|------|
| Session 持久化 | 文件系统存储，DB 存路径引用 | 灵活、安全、避免 DB 存大文件 |
| Branch/MR 策略 | 一个 Issue 一个 branch + 一个 MR | 与 session 复用匹配，commit 累积 |
| 调度粒度 | Task 层面调度，Issue 不参与 | Issue 是需求描述，不是调度单元 |
| 重试行为 | 新建 task，复制 prompt，不可修改 | 保留错误记录，修改 prompt 用追加任务 |
| Issue 独立性 | Codify Issue 独立于 GitLab Issue | GitLab issue 触发功能先不做 |
| Issue 状态流转 | 自动推断 (OPEN→IN_PROGRESS→COMPLETED) | 减少手动操作 |
| Multica 评估 | 不采用，继续发展 Codify | 需求不匹配（无 Docker 隔离、无调度、不同技术栈） |
| 重构策略 | 一次性全面重构 | 系统未上线，无需平滑过渡 |

## Data Model

### Issue 模型 (新增)

```python
class IssueStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"

class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)  # 同时作为 task 的默认 prompt
    project_id = Column(Integer, nullable=False, index=True)
    status = Column(Enum(IssueStatus), default=IssueStatus.OPEN, index=True)

    # Branch & MR (从 Task 提升到 Issue 层)
    branch_name = Column(String(255), nullable=True)   # 如 codify/issue-{id}
    base_branch = Column(String(255), nullable=True)    # 基于哪个分支创建
    target_branch = Column(String(255), nullable=True)  # MR 目标分支，NULL = 无 MR 模式

    merge_request_iid = Column(Integer, nullable=True)
    merge_request_url = Column(String(512), nullable=True)

    # Claude Session
    claude_session_id = Column(String(255), nullable=True)  # 首个 task 完成后设置
    session_storage_path = Column(String(512), nullable=True)  # 主机文件系统路径

    # 创建者
    initiator_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    initiator_username = Column(String(255), nullable=True)

    # 时间
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    tasks = relationship("Task", back_populates="issue", order_by="Task.created_at")

    __table_args__ = (
        Index("ix_issues_status_created", "status", "created_at"),
        Index("ix_issues_project_status", "project_id", "status"),
    )
```

### Task 模型变更

```python
class Task(Base):
    # 新增字段
    issue_id = Column(Integer, ForeignKey("issues.id"), nullable=False, index=True)
    is_retry = Column(Boolean, default=False)
    retry_source_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    # 保留字段
    id, project_id, user_prompt, status, priority, scheduled_at
    container_id, error_message, commit_sha
    additions, deletions, total_changes
    input_tokens, output_tokens, model_name
    merge_request_title, retry_count
    created_at, updated_at, started_at, completed_at

    # 删除字段 (提升到 Issue)
    # branch_name → Issue.branch_name
    # base_branch → Issue.base_branch
    # target_branch → Issue.target_branch
    # merge_request_iid → Issue.merge_request_iid
    # merge_request_url → Issue.merge_request_url
    # issue_iid → 替换为 issue_id (FK to Codify Issue)
    # issue_id (GitLab) → 删除
    # note_id → 删除 (webhook 触发暂不需要)
    # is_manual → 删除

    # 关系
    issue = relationship("Issue", back_populates="tasks")
    retry_source = relationship("Task", remote_side=[id])
```

### 数据库迁移

迁移编号: `022_issue_task_mr_refactoring.py`

操作:
1. 创建 `issues` 表
2. 修改 `tasks` 表：新增 `issue_id`, `is_retry`, `retry_source_task_id`
3. 删除 `tasks` 表的废弃字段: `branch_name`, `base_branch`, `target_branch`, `merge_request_iid`, `merge_request_url`, `issue_iid`, `issue_id` (旧), `note_id`, `is_manual`
4. 更新索引

## Session Management

### 存储结构

```
/var/codify/sessions/              ← 配置项: SESSION_STORAGE_ROOT
  └── <issue_id>/
      └── claude/                  ← 映射为容器内 /home/codify/.claude/
          └── projects/
              └── -workspace/      ← Claude 按 cwd 绝对路径哈希
                  └── <session-id>.jsonl
```

### Session 生命周期

**首次 Task（Issue 无 session）：**

1. Worker 创建容器，挂载空的 session 目录
2. 容器运行:
   ```bash
   claude -p \
     --dangerously-skip-permissions \
     --output-format text \
     --max-turns ${CLAUDE_MAX_TURNS} \
     --model ${ANTHROPIC_MODEL} \
     "${USER_PROMPT}"
   ```
   注意: **去掉 `--no-session-persistence`**
3. Claude 自动保存 session 到 `~/.claude/`
4. entrypoint.sh 提取 session ID:
   ```bash
   # 从 ~/.claude/projects/ 找到最新的 .jsonl 文件名即为 session-id
   SESSION_ID=$(ls -t ~/.claude/projects/*//*.jsonl | head -1 | xargs basename | sed 's/.jsonl//')
   echo "CODIFY_SESSION_ID:${SESSION_ID}"
   ```
5. Worker 解析 `CODIFY_SESSION_ID:` 标记，更新 Issue 的 `claude_session_id`
6. Session 文件通过 volume mount 已经在主机目录中

**后续 Task（Issue 有 session）：**

1. Worker 创建容器，挂载已有的 session 目录（含历史 session 文件）
2. 容器运行:
   ```bash
   claude -r ${CLAUDE_SESSION_ID} -p \
     --dangerously-skip-permissions \
     --output-format text \
     --max-turns ${CLAUDE_MAX_TURNS} \
     --model ${ANTHROPIC_MODEL} \
     "${USER_PROMPT}"
   ```
3. Session 文件自动更新（volume mount 写透）
4. 提取 session ID（可能不变，验证即可）

### 新增配置项

```
SESSION_STORAGE_ROOT=/var/codify/sessions   # session 文件存储根目录
```

在 `config.py` 的 `Settings` 中添加，可通过环境变量配置。

## Backend API

### Issue API (`backend/app/api/issues.py` 新增)

```
POST   /api/issues
  Request:  { title, description, project_id, base_branch?, target_branch? }
  Response: { issue }
  行为: 创建 Issue, 自动生成 branch_name = "codify/issue-{id}"

GET    /api/issues
  Query:    ?status=open&project_id=1&page=1&page_size=20
  Response: { items: [issue], total, page, page_size }

GET    /api/issues/{id}
  Response: { issue, tasks: [task] }  (含所有子 task)

PATCH  /api/issues/{id}
  Request:  { title?, description?, status? }
  Response: { issue }

POST   /api/issues/{id}/close
  行为: 设置 status = CLOSED
  Response: { issue }
```

### Task API 修改

```
POST   /api/tasks  (修改)
  Request:  { issue_id, user_prompt?, priority?, scheduled_at? }
  默认行为: user_prompt 为空时使用 Issue.description
  Response: { task }

POST   /api/tasks/{id}/retry  (修改)
  行为: 创建新 task, 复制原 prompt, is_retry=true, retry_source_task_id=原id
  参数: { scheduled_at? }  (可选预约)
  Response: { new_task }

GET    /api/tasks  (修改)
  新增 Query 参数: ?issue_id=12
  Response 增加 issue 关联信息
```

### 删除的 API

```
POST   /api/webhook/gitlab  → 移除 (暂不支持 webhook 触发)
POST   /api/tasks/{id}/execute  → 合并到调度逻辑
```

### Dashboard API (`backend/app/api/stats.py` 修改)

```
GET    /api/stats  (修改)
  新增返回: issue_count, issue_by_status, recent_issues
  保留: task_count, task_by_status, etc.
```

## Scheduler Changes

### Issue Mutex

```python
# 旧: _running_issues = set()  # "project_id:issue_iid" pairs
# 新: _running_issues = set()  # issue_id integers

# 检查: 同一 Issue 下的 task 不能并行执行
issue_key = task.issue_id
if issue_key in self._running_issues:
    continue  # 跳过，等待当前 task 完成
```

### Issue 状态自动流转

```python
# 在 _execute_task() 中:
async def _update_issue_status(self, db, task):
    issue = await db.get(Issue, task.issue_id)

    # OPEN → IN_PROGRESS (有 task 开始运行)
    if issue.status == IssueStatus.OPEN:
        issue.status = IssueStatus.IN_PROGRESS

# 在 task 完成后:
async def _on_task_completed(self, db, task):
    issue = await db.get(Issue, task.issue_id)
    # 检查是否所有 task 都已完成
    pending = await db.execute(
        select(Task).where(
            Task.issue_id == task.issue_id,
            Task.status.not_in([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED])
        )
    )
    if not pending.scalars().first():
        # 所有 task 都结束了，检查最后一个是否成功
        if task.status == TaskStatus.COMPLETED:
            issue.status = IssueStatus.COMPLETED
```

### Crash Recovery 更新

- 容器命名模式更新: `codify-{task_id}-issue{issue_id}` (替代 `codify-{task_id}-p{project_id}-i{issue_iid}`)
- 恢复逻辑基于 Issue 而非 project+issue_iid

## Worker Changes

### WorkerExecutor 修改

```python
async def execute_task(self, db, task_id):
    task = await db.get(Task, task_id)
    issue = await db.get(Issue, task.issue_id)

    # 从 Issue 获取 branch/MR 信息
    branch_name = issue.branch_name
    target_branch = issue.target_branch

    # Session 管理
    session_dir = issue.session_storage_path or f"{SESSION_STORAGE_ROOT}/{issue.id}/claude/"
    claude_session_id = issue.claude_session_id  # None for first task

    # 确保 session 目录存在
    os.makedirs(session_dir, exist_ok=True)

    # Docker 挂载: session 目录 → /home/codify/.claude/
    volumes = {
        session_dir: {"bind": "/home/codify/.claude/", "mode": "rw"},
        # ... 其他挂载
    }

    # 环境变量
    env = {
        "CLAUDE_SESSION_ID": claude_session_id or "",
        "ISSUE_ID": str(issue.id),
        # ... 其他变量
    }

    # 容器命名
    container_name = f"codify-{task_id}-issue{issue.id}"
```

### entrypoint.sh 修改

```bash
# 新增: Session resume 逻辑
if [ -n "${CLAUDE_SESSION_ID}" ]; then
    # 后续 task: resume 已有 session
    CLAUDE_CMD="claude -r ${CLAUDE_SESSION_ID} -p \
        --dangerously-skip-permissions \
        --output-format text \
        --max-turns ${CLAUDE_MAX_TURNS} \
        --model ${ANTHROPIC_MODEL}"
else
    # 首次 task: 新建 session
    CLAUDE_CMD="claude -p \
        --dangerously-skip-permissions \
        --output-format text \
        --max-turns ${CLAUDE_MAX_TURNS} \
        --model ${ANTHROPIC_MODEL}"
fi

# 去掉 --no-session-persistence

# 执行后提取 session ID
SESSION_FILE=$(find /home/codify/.claude/projects/ -name "*.jsonl" -newer /tmp/task_start 2>/dev/null | head -1)
if [ -n "${SESSION_FILE}" ]; then
    SESSION_ID=$(basename "${SESSION_FILE}" .jsonl)
    echo "CODIFY_SESSION_ID:${SESSION_ID}"
fi
```

## Frontend Design

### 路由结构

```
/dashboard              → Dashboard (Overview 风格, 重新设计)
/issues                 → Issue 列表页 (新增)
/issues/create          → 创建 Issue 页 (新增)
/issues/:id             → Issue 详情页 (新增, 含创建 task)
/tasks                  → Task 列表页 (保留, 增加 Issue 列)
/tasks/:id              → Task 详情页 (保留, 增加 Issue 链接)
/monitor                → 容器监控 (保留)
/analytics              → 分析 (保留)
/schedule-overview      → 排程总览 (保留)
/sessions               → 用户 Session 管理 (保留)
/configuration          → 配置 (保留)
/access-management      → 权限管理 (保留)
```

### Dashboard 重设计

```
┌──────────────────────────────────────────────────────┐
│  Dashboard                            [+ 新建 Issue] │
├──────────────────────────────────────────────────────┤
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                │
│  │Issues│ │ Tasks│ │Running│ │ Done │                │
│  │  12  │ │  45  │ │   2  │ │  38  │                │
│  └──────┘ └──────┘ └──────┘ └──────┘                │
│                                                      │
│  ┌─ Activity ──────────────────────────────────────┐ │
│  │ ████ ██ █████ ███ ██████ (GitHub 风格热力图)      │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─ 最近 Issues ─────────────────────────────────┐  │
│  │ #12 实现用户登录    IN_PROGRESS  3 tasks       │  │
│  │ #11 修复支付Bug     COMPLETED    2 tasks       │  │
│  │ #10 重构API        OPEN          0 tasks       │  │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─ 进行中的任务 ───────────────────────────────┐   │
│  │ Task #45 (Issue #12) running  2m ago          │   │
│  │ Task #44 (Issue #12) queued   5m ago          │   │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### Issue 列表页 (`/issues`)

新增 `IssueList.vue`:
- 分页表格: ID, 标题, 状态, 项目, Task 数量, 创建时间
- 过滤: 状态、项目
- 点击跳转 Issue 详情

### Issue 详情页 (`/issues/:id`)

新增 `IssueView.vue`:
- 顶部: Issue 元信息 (标题, 状态, 项目, 分支, MR 链接, Session ID)
- 中部: Issue 描述
- 底部: Task 列表 + 内嵌创建 Task 表单
  - 提示词默认使用 Issue 描述，可修改
  - 优先级选择
  - 调度选项 (立即 / 预约)
- 操作按钮: 编辑 Issue, 关闭 Issue
- 每个 Task 行: 状态, prompt 摘要, 时间, 操作按钮 (重试/取消)

### 创建 Issue 页 (`/issues/create`)

新增 `CreateIssue.vue`:
- 表单字段: 项目(下拉), 标题, 描述, 基础分支(下拉), 目标分支(下拉)
- 可选: 创建后立即创建首个任务 (checkbox)
- 提交后跳转 Issue 详情页

### 现有页面修改

**Task 列表 (原 Dashboard 任务列表):**
- 新增 "Issue" 列，显示 Issue 标题，点击跳转
- 新增 `issue_id` 筛选

**Task 详情 (TaskView.vue):**
- 元信息区增加"所属 Issue"链接
- 分支/MR 信息从 Issue 获取

**导航栏:**
- 新增 "Issues" 导航项
- 保留 "Tasks" 导航项

### 新增 TypeScript 类型

```typescript
interface Issue {
  id: number
  title: string
  description: string | null
  project_id: number
  status: IssueStatus
  branch_name: string | null
  base_branch: string | null
  target_branch: string | null
  merge_request_iid: number | null
  merge_request_url: string | null
  claude_session_id: string | null
  initiator_user_id: number | null
  initiator_username: string | null
  created_at: string
  updated_at: string
  tasks?: Task[]        // 详情接口返回
  task_count?: number   // 列表接口返回
}

type IssueStatus = 'open' | 'in_progress' | 'completed' | 'closed'

interface CreateIssueRequest {
  title: string
  description?: string
  project_id: number
  base_branch?: string
  target_branch?: string
}

// Task 类型新增字段
interface Task {
  // ... 保留现有字段
  issue_id: number        // 新增
  is_retry: boolean       // 新增
  retry_source_task_id: number | null  // 新增
  issue?: Issue           // 新增, 关联查询时返回
}
```

### i18n 更新

`en.ts` 和 `zh-CN.ts` 新增:

```
nav.issues → "Issues" / "需求"
issue.title → "Issue" / "需求"
issue.create → "Create Issue" / "创建需求"
issue.list → "Issues" / "需求列表"
issue.detail → "Issue Detail" / "需求详情"
issue.status.* → 状态翻译
issue.createTask → "Create Task" / "创建任务"
issue.retry → "Retry" / "重试"
issue.close → "Close Issue" / "关闭需求"
dashboard.recentIssues → "Recent Issues" / "最近的需求"
dashboard.activity → "Activity" / "活动"
dashboard.createIssue → "New Issue" / "新建需求"
```

## Scope Exclusions

以下功能在本次重构中**不包含**:

1. **GitLab Issue webhook 触发** — 不实现 GitLab Issue → Codify Issue 的自动创建
2. **GitLab 评论通知** — 不发送 bot 评论到 GitLab Issue
3. **Webhook 端点** — `/api/webhook/gitlab` 暂时移除
4. **MR 评论触发** — 不支持在 MR 评论中触发新任务

## File Change Summary

### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/api/issues.py` | Issue CRUD API |
| `backend/alembic/versions/022_issue_task_mr_refactoring.py` | 数据库迁移 |
| `frontend/src/views/IssueList.vue` | Issue 列表页 |
| `frontend/src/views/IssueView.vue` | Issue 详情页 |
| `frontend/src/views/CreateIssue.vue` | 创建 Issue 页 |

### 重大修改文件

| 文件 | 变更 |
|------|------|
| `backend/app/models.py` | 新增 Issue 模型, 修改 Task 模型 |
| `backend/app/api/tasks.py` | Task 创建需要 issue_id, 重试逻辑变更 |
| `backend/app/scheduler.py` | Issue mutex, Issue 状态自动流转 |
| `backend/app/core/worker.py` | Session 管理, 从 Issue 读取 branch/MR 信息 |
| `backend/app/config.py` | 新增 SESSION_STORAGE_ROOT 配置 |
| `deploy/entrypoint.sh` | Session resume 支持, 去掉 --no-session-persistence |
| `frontend/src/api/index.ts` | Issue API 函数, Issue 类型 |
| `frontend/src/router/index.ts` | 新增 Issue 路由 |
| `frontend/src/views/Dashboard.vue` | 重新设计为 Overview 风格 |
| `frontend/src/views/TaskView.vue` | 增加 Issue 链接 |
| `frontend/src/i18n/messages/en.ts` | Issue 相关翻译 |
| `frontend/src/i18n/messages/zh-CN.ts` | Issue 相关翻译 |

### 删除/移除

| 文件 | 变更 |
|------|------|
| `backend/app/api/webhook.py` | 移除或注释掉 webhook 处理逻辑 |
| `frontend/src/views/CreateTask.vue` | 可能删除 (功能合并到 IssueView) |
