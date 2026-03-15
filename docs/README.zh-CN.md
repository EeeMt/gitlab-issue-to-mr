# GitLab Issue to MR Bot (GIMR)

[English README](../README.md)

GIMR 是一个基于 GitLab Issue 的 AI 代码生成服务。用户在 Issue 中评论 `@ai-bot <需求>` 后，系统会自动创建任务、调度 Worker 容器执行 Claude CLI、提交代码并发起 Merge Request。同时项目还提供了一个 Vue 管理后台，用于任务管理、调度、监控、统计分析、配置管理以及基于 GitLab OIDC 的访问控制。

## 功能概览

- 监听 GitLab Issue 评论 Webhook，例如 `@ai-bot <prompt>`
- 支持任务创建、优先级调度、延迟执行
- 每个任务在独立 Docker 容器中运行
- 使用兼容 Claude CLI 的模型后端生成并修改代码
- 自动创建或更新 MR，并把任务进度回写到 GitLab
- 提供 Web 管理后台：任务、日志、监控、统计、配置、诊断
- 支持 GitLab OIDC 登录、服务端会话、按项目访问控制
- 前端支持中英文切换（`English` / `简体中文`）

## 高层流程

1. GitLab 将 Issue 评论事件发送到 `/api/webhook/gitlab`
2. 后端解析命令并创建 `Task`
3. 调度器按状态、优先级、计划时间和并发限制挑选可执行任务
4. Worker 执行器启动独立 Docker 容器
5. 容器克隆仓库、执行 Claude CLI、提交代码、推送分支并更新 MR
6. Dashboard 用于查看任务、日志、容器、统计、配置和认证状态

关键组件：

- `backend/app/api/webhook.py`：GitLab Webhook 入口
- `backend/app/api/tasks.py`：任务 API、筛选、计划任务队列、项目列表
- `backend/app/core/worker.py`：任务执行与 MR 更新
- `backend/app/scheduler.py`：优先级调度与崩溃恢复
- `backend/app/api/auth.py`：OIDC 认证 / 会话状态接口
- `backend/app/api/config.py`：运行时配置与认证配置接口

## 当前 Dashboard 页面

- 任务列表（支持项目 / 发起人筛选）
- 手动创建任务
- 任务详情与日志
- 调度总览
- 统计分析
- 监控页面
- 会话管理
- 系统配置页面（路由：`/configuration`）
- 访问管理
- OIDC 诊断

## 目录结构

```text
docs/
  README.md
  README.zh-CN.md
  DEPLOYMENT.md
  DEVELOPMENT.md
  GITLAB_WEBHOOK_SETUP.md
  GITLAB_OIDC_SETUP.md
  DESIGN.md
  PROGRESS.md
  e2e-debugging.md
backend/
  app/
  alembic/
  tests/
deploy/
  docker-compose.yml
  Dockerfile.backend
  Dockerfile.frontend
  Dockerfile.worker
frontend/
```

## 快速开始

### 前置条件

- Docker 与 Docker Compose
- 可访问的 GitLab 实例
- 可供 Claude CLI 使用的模型服务
- PostgreSQL 由 `deploy/docker-compose.yml` 提供

### 1. 准备配置

本地开发后端可以从模板开始：

```bash
cp backend/.env.example backend/.env
```

对于默认 Docker 部署，`deploy/docker-compose.yml` 当前会给 `backend` 和 `scheduler` 加载 `deploy/.env.test`。至少需要准备这些配置项：

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `GITLAB_WEBHOOK_SECRET`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `CONFIG_ENCRYPTION_KEY`
- `SECRET_KEY` / 会话相关密钥

重要说明：

- OIDC 与其他运行时配置会持久化到 PostgreSQL 的 `system_config`
- 在配置页面输入的敏感配置会以加密形式存储
- 如果 PostgreSQL volume 被删除，运行时配置、OIDC 配置、用户、会话、审计数据都会丢失

### 2. 启动服务

```bash
cd deploy
docker-compose up -d --build
```

默认会启动：

- `postgres`
- `backend`
- `scheduler`
- `nginx`

默认暴露端口：

- 前端：`http://localhost:8880`
- 后端 API：`http://localhost:8000`

### 3. 配置 GitLab Webhook

见 [GITLAB_WEBHOOK_SETUP.md](GITLAB_WEBHOOK_SETUP.md)。

### 4. 配置 Dashboard 登录（推荐）

见 [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)。

推荐上线顺序：

1. 初次部署先保持 OIDC 关闭
2. 确保部署环境提供有效的 `CONFIG_ENCRYPTION_KEY`
3. 打开 Dashboard 的 **Configuration** 页面
4. 填写 OIDC 参数
5. 使用内置诊断 / 测试能力验证
6. 验证成功后再启用 OIDC

## 开发命令

### 后端

```bash
# 安装依赖
cd backend && pip install -r requirements.txt

# 本地运行后端
cd backend && uvicorn app.main:app --reload

# 手动执行迁移
cd backend && alembic upgrade head
```

### 前端

```bash
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run build
```

### 部署时重建镜像

修改代码后，按影响面重建对应镜像：

```bash
# backend / scheduler
docker build -f deploy/Dockerfile.backend -t deploy-backend .
cd deploy && docker-compose up -d backend scheduler

# frontend nginx
cd frontend && npm run build
cd ../deploy && docker-compose build nginx && docker-compose up -d nginx

# worker（当 worker 镜像内容发生变化时）
docker build -f deploy/Dockerfile.worker -t gitlab-issues-to-mr-worker:latest .
```

## 测试

### 常用测试命令

```bash
# 全量 backend 测试
cd backend && pytest

# 单元测试
cd backend && pytest tests/unit/ -v

# Mock E2E
cd backend && pytest tests/mock_e2e/ -v

# 真实 GitLab E2E
cd backend && pytest tests/gitlab_e2e/ -v

# 前端构建校验
cd frontend && npm run build
```

### 测试安全提示

真实集成测试请只在隔离的测试环境中运行。

原因：

- 运行时配置、认证配置、用户、会话都保存在 PostgreSQL 中
- 删除 PostgreSQL Docker volume 会导致整库重置
- 不应在共享环境里运行带破坏性清理动作的脚本

如需排查 E2E，请同时阅读 [e2e-debugging.md](e2e-debugging.md)。

## 使用方式

### GitLab Issue 工作流

1. 在 GitLab 中创建 Issue
2. 添加评论，例如：

```text
@ai-bot create a hello world function
```

3. GIMR 会：
   - 创建或入队任务
   - 创建分支
   - 在 Worker 容器中执行 Claude CLI
   - 提交并推送代码
   - 创建或更新 Merge Request
   - 把进度回写到 GitLab

### 手动任务

也可以直接在 Dashboard 中创建任务，不依赖 GitLab Issue。手动任务不会向 GitLab Issue 发送开始 / 完成通知，适合运维或人工触发的代码生成任务。

## 运维说明

- `deploy/docker-compose.yml` 中，backend 和 scheduler 共用同一个 backend 镜像
- 默认 compose 配置里，backend 使用 `AUTO_MIGRATE=false`，scheduler 使用 `AUTO_MIGRATE=true`
- 配置页面前端路由为 `/configuration`
- 共享页面权限可将部分只读页面开放给非管理员
- 认证用户看到的项目和任务会按 GitLab 可访问范围过滤

## 相关文档

- [DEPLOYMENT.md](DEPLOYMENT.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)
- [GITLAB_WEBHOOK_SETUP.md](GITLAB_WEBHOOK_SETUP.md)
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)
- [e2e-debugging.md](e2e-debugging.md)
- [DESIGN.md](DESIGN.md)

## License

MIT
