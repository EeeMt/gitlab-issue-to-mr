# 开发进度文档

## 项目概述

GitLab Issue to MR Bot (GIMR) - 基于 GitLab Issue 自动生成代码并创建 MR 的 AI 助手。

## 当前状态

**阶段**: MVP + P1 + P2 + 稳定性增强 已完成，端到端集成测试通过 ✅

**当前任务**: P0.1 分步规划与执行 ✅ 已完成

---

## 已完成功能

### 1. 项目初始化 ✅

| 任务 | 状态 | 文件 |
|------|------|------|
| 创建项目目录结构 | ✅ | `backend/app/`, `backend/app/api/`, `backend/app/core/`, `deploy/` |
| Python 依赖配置 | ✅ | `backend/requirements.txt`, `backend/pyproject.toml` |
| Docker 环境配置 | ✅ | `deploy/Dockerfile.backend`, `deploy/docker-compose.yml` |
| Alembic 配置 | ✅ | `backend/alembic.ini`, `backend/alembic/env.py` |
| 环境变量模板 | ✅ | `backend/.env.example` |

### 2. 基础设施 ✅

| 任务 | 状态 | 文件 |
|------|------|------|
| 配置管理模块 | ✅ | `backend/app/config.py` |
| 数据库连接 | ✅ | `backend/app/database.py` |
| 数据模型 | ✅ | `backend/app/models.py` |
| Alembic 迁移 | ✅ | `backend/alembic/versions/001_initial.py` |
| FastAPI 入口 | ✅ | `backend/app/main.py` |

### 3. 核心功能 - Webhook ✅

| 任务 | 状态 | 文件 |
|------|------|------|
| Webhook handler | ✅ | `backend/app/api/webhook.py` |
| 解析 @ai-bot 指令 | ✅ | `backend/app/core/parser.py` |
| 幂等性校验 | ✅ | `backend/app/api/webhook.py` (note_id 唯一约束) |
| 任务创建 | ✅ | `backend/app/api/webhook.py` |

### 4. 核心功能 - Worker ✅

| 任务 | 状态 | 文件 |
|------|------|------|
| Docker 客户端封装 | ✅ | `backend/app/core/docker_client.py` |
| GitLab 客户端封装 | ✅ | `backend/app/core/gitlab_client.py` |
| Worker 镜像 | ✅ | `deploy/Dockerfile.worker`, `deploy/entrypoint.sh` |
| Worker 执行器 | ✅ | `backend/app/core/worker.py` |
| MR 创建与 Issue 回复 | ✅ | `deploy/entrypoint.sh` |

### 5. 文档 ✅

| 任务 | 状态 | 文件 |
|------|------|------|
| GitLab Webhook 配置文档 | ✅ | `GITLAB_WEBHOOK_SETUP.md` |
| README | ✅ | `README.md` |

---

## 技术实现细节

### Webhook 端点

- **URL**: `POST /api/webhook/gitlab`
- **验证**: X-Gitlab-Token header
- **触发条件**: Issue 评论包含 `@ai-bot` 指令

### 命令解析

支持格式:
- `@ai-bot <prompt>`
- `@ai-bot: <prompt>`

### Git 认证方案

使用 Personal Access Token 嵌入 URL 方式:

```bash
# Clone
GIT_REPO_URL="https://${TOKEN}@gitlab.example.com/project/${PROJECT_ID}.git"
git clone "${GIT_REPO_URL}" /workspace

# Push
git remote set-url origin "${GIT_REPO_URL}"
git push -u origin "${BRANCH_NAME}"
```

### Worker 流程

1. Clone 仓库 (带认证)
2. 创建/切换分支
3. 调用 Claude CLI 生成代码
4. Commit 并 Push
5. 创建 MR
6. 评论 Issue

---

## 测试结果

### 本地单元测试 ✅ (已完成)

| 测试类别 | 测试数 | 状态 |
|---------|--------|------|
| Parser 命令解析 | 12 | ✅ |
| 数据模型 | 3 | ✅ |
| Webhook 解析 | 5 | ✅ |
| 任务状态 | 8 | ✅ |
| 并发控制 | 6 | ✅ |
| 延迟计算 | 11 | ✅ |
| E2E 模拟 | 3 | ✅ |
| 超时与崩溃恢复 | 5 | ✅ |

**总计: 53 个测试用例全部通过**

### Docker 环境测试 ✅ (已完成)

| 测试项 | 状态 |
|--------|------|
| Docker Compose 启动 | ✅ |
| 后端服务运行 (port 8000) | ✅ |
| PostgreSQL 连接 | ✅ |
| Root 端点 `/` | ✅ |
| Health 端点 `/health` | ✅ |

### 端到端集成测试 ✅ (2026-03-10)

| 测试项 | 状态 | 说明 |
|--------|------|------|
| Docker Compose 启动 | ✅ | PostgreSQL + Backend 正常启动 |
| GitLab API 连接 | ✅ | 可访问 http://192.168.50.129:8080 |
| 数据库迁移 | ✅ | alembic upgrade head 成功 |
| Issue 创建 | ✅ | 通过 GitLab API 创建 Issue |
| @ai-bot 命令解析 | ✅ | Webhook 正确解析命令 |
| Task 创建 | ✅ | Task 创建成功 |
| Worker 容器执行 | ✅ | 容器成功拉起并执行 |
| 代码提交 | ✅ | 分支创建成功 |
| MR 创建 | ✅ | MR 创建成功 |
| Issue 关联 | ✅ | MR 配置了 `Closes #issue` |

**测试脚本**:
- `backend/test_integration_e2e.py` - 真实 GitLab 端到端测试
- `backend/test_integration_e2e_mock.py` - Mock 模式测试

**使用方式**:
```bash
# 完整测试
python3 backend/test_integration_e2e.py

# 跳过 Docker 启动
python3 backend/test_integration_e2e.py --skip-startup

# 保持服务运行
python3 backend/test_integration_e2e.py --keep-running

# Mock 模式测试
python3 backend/test_integration_e2e_mock.py --skip-startup
```

---

### 单元测试 ✅ (历史)

---

## 已知问题

无 - 端到端集成测试已通过 ✅

### 修复记录

- 2026-03-08: 修复 Alembic `env.py` 对私有属性 `config._sections` 的错误访问
- 2026-03-08: 修复 Alembic 枚举迁移（避免 `taskstatus` 重复创建，补齐 queued/cancelled）
- 2026-03-08: 修复 SQLAlchemy Enum 映射（存储枚举值而非 `PENDING` 大写名称）
- 2026-03-08: 修复 Docker Client 初始化（`docker.from_env` 参数错误，改为 `docker.DockerClient`）
- 2026-03-08: 修复 Scheduler 启动恢复逻辑（仅清理 Worker 容器，避免误处理 compose 服务容器）
- 2026-03-08: 修复 Scheduler 在迁移前启动导致的中断（启动恢复失败降级处理）
- 2026-03-08: 修复配置读取大小写问题（`case_sensitive=False`，使 Docker/DB 环境变量生效）
- 2026-03-09: 添加超时与崩溃恢复测试用例（5个测试，覆盖超时检测、容器清理、状态修复）
- 2026-03-10: 添加端到端集成测试脚本 (test_integration_e2e.py, test_integration_e2e_mock.py)
- 2026-03-10: 修复 note_id int32 范围问题
- 2026-03-10: 端到端集成测试通过（真实 GitLab + Worker 容器执行 + MR 创建）

---

## 配置要求

### 环境变量

```bash
# Backend
BACKEND_URL=http://localhost:8000  # 后端服务地址

# GitLab
GITLAB_URL=https://gitlab.example.com
GITLAB_BOT_TOKEN=glpat-xxx  # 需要 api, read_repository, write_repository 权限
GITLAB_WEBHOOK_SECRET=your-secret

# Claude CLI
ANTHROPIC_BASE_URL=http://host.docker.internal:11434/v1
ANTHROPIC_API_KEY=your-key
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://gimr:gimr_password@postgres:5432/gimr

# Docker Engine
DOCKER_HOST=tcp://docker.example.com:2376

# Worker
WORKER_IMAGE=gitlab-issues-to-mr-worker:latest

# 调度配置 (P1)
MAX_CONCURRENCY=3              # 最大并发任务数
TASK_TIMEOUT=1800             # 任务超时时间(秒)
SCHEDULER_INTERVAL=5           # 调度器轮询间隔(秒)
DEFAULT_TARGET_BRANCH=main     # 默认目标分支
```
```

### GitLab 配置

1. 创建 Personal Access Token (需要 `api`, `read_repository`, `write_repository` 权限)
2. 在项目中配置 Webhook:
   - URL: `{backend_url}/api/webhook/gitlab`
   - Secret: `GITLAB_WEBHOOK_SECRET`
   - Trigger: Issue comments

---

## 文件清单

```
backend/
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── webhook.py          # Webhook 端点
│   ├── core/
│   │   ├── __init__.py
│   │   ├── docker_client.py    # Docker 客户端
│   │   ├── gitlab_client.py    # GitLab 客户端
│   │   ├── parser.py           # @ai-bot 命令解析 (P1 扩展)
│   │   └── worker.py           # Worker 执行器 (P1 扩展)
│   ├── config.py               # 配置管理 (P1 扩展)
│   ├── database.py             # 数据库连接
│   ├── main.py                 # FastAPI 入口 (P1 扩展)
│   ├── models.py               # 数据模型 (P1 扩展)
│   └── scheduler.py            # 任务调度器 (P1 新增)
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 001_initial.py       # 初始迁移
│       └── 002_queue_scheduling.py  # P1 迁移
├── requirements.txt
├── pyproject.toml
├── alembic.ini
├── .env.example
├── test_timeout_recovery.py    # 超时与崩溃恢复测试
├── test_e2e.py                # 端到端模拟测试
├── test_p1.py                 # P1 功能测试
├── test_webhook.py            # Webhook 测试
├── test_integration_e2e.py    # 真实 GitLab 端到端集成测试
└── test_integration_e2e_mock.py  # Mock 模式端到端集成测试

deploy/
├── Dockerfile.backend
├── Dockerfile.worker
├── docker-compose.yml
└── entrypoint.sh               # Worker 入口脚本

README.md
GITLAB_WEBHOOK_SETUP.md
PROGRESS.md                     # 本文档
```

---

## 已知问题

1. 需要真实 GitLab 地址 + Token 才能验证成功创建 MR 的 happy path（当前仅验证失败路径与状态回写）。

---

## 稳定性增强 ✅ 已完成

### 目标

提升系统稳定性，增强错误处理和监控能力。

### 任务列表

| # | 任务 | 状态 |
|---|---|---|
| 2.1 | 完善 Worker 错误处理 (超时、容器异常、GitLab API 错误) | ✅ |
| 2.2 | 优化日志输出 (结构化日志) | ✅ |
| 2.3 | 添加健康检查端点 (/health) | ✅ |
| 2.4 | 添加失败任务告警通知 | ✅ |
| 2.5 | 添加任务自动重试机制 | ✅ |

---

## P0.1 分步规划与执行 ✅ 已完成

### 目标

增强用户体验，提供可追踪的实现过程。先规划实现方案，再逐步执行，实时更新 MR 进度。

### 任务列表

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 3.1 | 后端：创建初始 MR 并传递 MR_IID | ✅ | `backend/app/core/worker.py` |
| 3.2 | Worker：接收 MR_IID 并更新 MR 描述 | ✅ | `deploy/entrypoint.sh` |
| 3.3 | 逐步执行每个步骤 | ✅ | `deploy/entrypoint.sh` |
| 3.4 | 实时更新 MR 进度 | ✅ | `deploy/entrypoint.sh` |
| 3.5 | 生成完成报告 | ✅ | `deploy/entrypoint.sh` |
| 3.6 | P0.1 单元测试 | ✅ | `backend/test_p01.py` |

---

## P0.1 实现说明

P0.1 需要在 worker 执行前创建初始 MR，以便在执行过程中更新 MR 描述：
1. **后端**：在 `execute_task` 中，容器启动前先创建 Draft MR
2. **Worker**：接收 MR_IID 环境变量，在各阶段调用 GitLab API 更新 MR 描述

### 部署步骤

```bash
# 1. 重新构建 worker 镜像
cd deploy && docker-compose build worker

# 2. 重启服务
docker-compose up -d

# 3. 测试 P0.1 功能
# 在 GitLab Issue 中评论 @ai-bot <需求描述>
```

### 待优化项

- [ ] 添加更多错误场景测试
- [ ] 添加单元测试覆盖率报告
- [ ] 添加前端 UI 测试

---

# P1 - 队列调度 ✅ 已完成

## 目标

支持多任务并发、延迟执行、可靠的状态管理。

### 已完成功能

#### 1.1 数据模型扩展 ✅

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 1.1.1 | 添加 scheduled_at 字段 | ✅ | `app/models.py` |
| 1.1.2 | 添加 priority 字段 | ✅ | `app/models.py` |
| 1.1.3 | 添加 container_id 字段 | ✅ | `app/models.py` |
| 1.1.4 | 添加 target_branch 字段 | ✅ | `app/models.py` |
| 1.1.5 | 创建数据库迁移 | ✅ | `alembic/versions/002_queue_scheduling.py` |

#### 1.2 命令解析扩展 ✅

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 1.2.1 | 支持 priority 参数 | ✅ | `app/core/parser.py` |
| 1.2.2 | 支持 delay 参数 | ✅ | `app/core/parser.py` |
| 1.2.3 | 支持 cancel 指令 | ✅ | `app/api/webhook.py` |
| 1.2.4 | 支持 status 指令 | ✅ | `app/api/webhook.py` |

#### 1.3 任务调度器 ✅

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 1.3.1 | 创建 Scheduler 类 | ✅ | `app/scheduler.py` |
| 1.3.2 | 轮询 pending 任务 | ✅ | `app/scheduler.py` |
| 1.3.3 | Issue 级互斥 | ✅ | `app/scheduler.py` |
| 1.3.4 | 并发控制 | ✅ | `app/scheduler.py` |
| 1.3.5 | 延迟执行 | ✅ | `app/scheduler.py` |

#### 1.4 超时与崩溃恢复 ✅

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 1.4.1 | 超时检测 | ✅ | `app/core/worker.py` |
| 1.4.2 | 容器命名规范 | ✅ | `app/core/worker.py` |
| 1.4.3 | 启动时清理 | ✅ | `app/scheduler.py` |
| 1.4.4 | 状态修复 | ✅ | `app/scheduler.py` |

#### 1.5 配置扩展 ✅

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 1.5.1 | 添加调度配置 | ✅ | `app/config.py` |
| 1.5.2 | 添加 target_branch 配置 | ✅ | `app/config.py` |

#### 1.6 用户反馈通知 ✅ 已完成

| # | 任务 | 状态 | 文件 |
|---|---|---|---|
| 1.6.1 | 任务开始时发送 "开始处理" 通知 | ✅ | `app/core/worker.py` |
| 1.6.2 | 任务完成时发送 "MR已创建/失败" 通知 | ✅ | `app/core/worker.py` |
| 1.6.3 | 单元测试 | ✅ | `test_notifications.py` |

---

## 任务依赖图

```
1.1.1-1.1.4 数据模型扩展 ──► 1.1.5 数据库迁移
      │
      ▼
1.2 命令解析扩展 ◄──────────┘
      │
      ▼
1.3 任务调度器
      │
      ├──────────────────┐
      ▼                  ▼
1.4 超时与崩溃恢复    1.5 配置扩展
```

---

## 关键文件变更

### 新增文件

```
backend/app/
├── scheduler.py         # 任务调度器
├── core/
│   └── scheduler.py     # 调度逻辑
```

### 修改文件

```
backend/app/
├── config.py            # 添加调度配置
├── models.py            # 添加新字段
├── core/
│   ├── parser.py       # 扩展命令解析
│   └── worker.py       # 添加超时处理
├── api/
│   └── webhook.py      # 修改任务创建逻辑
├── alembic/
│   └── versions/
│       └── 002_queue_scheduling.py  # 新迁移
```

---

## 验证方式

- [x] 多个任务同时触发，验证并发控制生效
- [x] 同一 Issue 多次 @bot，验证互斥调度
- [x] 使用 delay 参数，验证延迟执行
- [x] 使用 priority 参数，验证优先级调度
- [x] 停止正在运行的任务，验证超时处理
- [x] 重启服务，验证崩溃恢复

---

## 环境变量新增

```bash
# 调度配置
MAX_CONCURRENCY=3              # 最大并发任务数
TASK_TIMEOUT=1800              # 任务超时时间(秒)
SCHEDULER_INTERVAL=5           # 调度器轮询间隔(秒)
DEFAULT_TARGET_BRANCH=main     # 默认目标分支
```
