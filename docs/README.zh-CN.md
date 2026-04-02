# Codify

[English README](../README.md)

Codify 是一个基于 GitLab Issue 的 AI 代码生成服务。用户在 Issue 评论中输入 `@ai-bot <需求>` 后，系统会创建任务、调度 Worker 容器执行 Claude CLI、提交代码并创建 Merge Request。项目同时提供一个 Web Dashboard，用于任务管理、调度、监控、统计、配置和访问控制。

## 它能做什么

- 监听 GitLab Issue 评论 Webhook，例如 `@ai-bot <prompt>`
- 支持优先级、延迟执行、重试和手动触发任务
- 每个任务都在独立 Docker 容器中运行
- 使用兼容 Claude CLI 的模型后端生成并修改代码
- 自动推送提交、创建或更新 MR，并把进度回写到 GitLab
- 提供 Dashboard 用于任务、日志、监控、统计、会话、配置和认证管理

## 请求流程

1. GitLab 将评论事件发送到 `/api/webhook/gitlab`
2. 后端解析命令并创建 `Task`
3. 调度器按状态、优先级、计划时间和并发限制挑选可执行任务
4. Worker 执行器启动独立 Docker 容器
5. 容器克隆仓库、执行 Claude CLI、提交代码、推送分支并更新 MR
6. Dashboard 用于查看任务状态、日志、容器、统计和配置

## 关键组件

- `backend/app/api/webhook.py` — GitLab Webhook 入口
- `backend/app/api/tasks.py` — 任务 API 与队列视图
- `backend/app/core/worker.py` — 任务执行与 MR 更新
- `backend/app/scheduler.py` — 优先级调度与崩溃恢复
- `backend/app/api/config.py` — 运行时与认证配置
- `frontend/src/views/` — Dashboard 页面
- `deploy/` — Dockerfile、Compose、Worker 启动脚本

## Dashboard 页面

- 任务列表
- 任务详情与日志
- 手动创建任务
- 调度总览
- 统计分析
- 监控页面
- 会话管理
- 系统配置
- 访问管理
- OIDC 诊断

## 快速开始

### 前置条件

- Docker 与 Docker Compose
- 可访问的 GitLab 实例
- 可供 Claude CLI 使用的模型服务

### 1. 准备配置

默认 Docker 部署中，`deploy/docker-compose.yml` 会给 `backend` 和 `scheduler` 加载 `deploy/.env.test`。

至少需要准备这些配置项：

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `GITLAB_WEBHOOK_SECRET`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `CONFIG_ENCRYPTION_KEY`
- `SECRET_KEY`
- `SESSION_SECRET`

说明：

- 运行时覆盖配置会持久化到 PostgreSQL 的 `system_config`
- 在 Dashboard 中录入的敏感配置会加密存储
- 如果 PostgreSQL volume 被删除，运行时配置、用户、会话和认证状态都会丢失

### 2. 启动服务

```bash
cd deploy
docker-compose up -d --build
```

默认端口：

- 前端：`http://localhost:8880`
- 后端 API：`http://localhost:8000`

### 3. 配置 GitLab Webhook

见 [GITLAB_WEBHOOK_SETUP.md](GITLAB_WEBHOOK_SETUP.md)。

### 4. 配置 Dashboard 登录（推荐）

见 [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)。

推荐顺序：

1. 初次部署先保持 OIDC 关闭
2. 确保配置了 `CONFIG_ENCRYPTION_KEY`
3. 打开 Dashboard 的 Configuration 页面
4. 填写并验证 OIDC 参数
5. 验证通过后再启用 OIDC

## 常用命令

### 后端

```bash
cd backend && pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && pytest
```

### 前端

```bash
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run build
```

### 重建部署镜像

```bash
# backend / scheduler
docker build -f deploy/Dockerfile.backend -t deploy-backend .
cd deploy && docker-compose up -d backend scheduler

# frontend / nginx
docker build -f deploy/Dockerfile.frontend -t codify-nginx:latest .
cd deploy && docker-compose up -d --build nginx

# worker
docker build -f deploy/Dockerfile.worker -t codify-worker:latest .
```

## 使用方式

### GitLab Issue 工作流

在 Issue 评论中输入：

```text
@ai-bot create a hello world function
```

Codify 会创建任务、启动 Worker、推送代码、创建或更新 MR，并把进度回写到 GitLab。

### 手动任务

也可以直接在 Dashboard 中创建任务。手动任务不会向 GitLab Issue 发送通知。

## 运维说明

- `deploy/docker-compose.yml` 中，`backend` 和 `scheduler` 共用同一个 backend 镜像
- 默认 Compose 中，`backend` 使用 `AUTO_MIGRATE=false`，`scheduler` 使用 `AUTO_MIGRATE=true`
- 配置页面路由为 `/configuration`
- 认证用户能看到的项目和任务会按 GitLab 权限过滤

## 相关文档

- [English README](../README.md)
- [文档索引](README.md)
- [USER_GUIDE.zh-CN.md](USER_GUIDE.zh-CN.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)
- [GITLAB_WEBHOOK_SETUP.md](GITLAB_WEBHOOK_SETUP.md)
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)
- [e2e-debugging.md](e2e-debugging.md)
- [SCREENSHOTS.md](SCREENSHOTS.md)
- [../deploy/offline-bundle/README.md](../deploy/offline-bundle/README.md)

## License

MIT
