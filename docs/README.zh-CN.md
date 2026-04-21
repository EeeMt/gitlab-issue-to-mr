# Codify

[English README](../README.md)

Codify 帮你把需求变成代码。写清楚目标和约束，剩下的交给 Codify——在隔离容器里生成代码、推送提交、开 MR。

通过预约调度，让 AI 全天候运转，充分利用时间和算力资源。整个过程在 Dashboard 里一目了然。

## 从需求到代码，三步搞定

1. **写需求** — 描述要解决的问题和期望结果
2. **发起任务** — 立即执行，或预约到空闲时段，让资源不闲置
3. **查看结果** — 跟踪状态、翻阅日志、检查交付物

## 幕后发生了什么

当你发起一个任务后，Codify 会：

1. 按优先级和预约时间排入调度队列，遵守并发限制
2. 启动一个独立的 Docker 容器
3. 在容器里克隆仓库、运行 Claude CLI 生成代码
4. 把改动提交、推送到新分支，创建或更新 MR
5. 全程在 Dashboard 记录日志和状态变化

## 系统功能概览


https://github.com/user-attachments/assets/19d0dd54-25d0-4449-9df1-aec66a04652d


## 关键组件

- `backend/app/api/tasks.py` — 任务 API 与队列视图
- `backend/app/api/issues.py` — 需求管理 API
- `backend/app/core/worker.py` — 任务执行与 MR 更新
- `backend/app/scheduler.py` — 优先级调度与崩溃恢复
- `backend/app/api/config.py` — 运行时与认证配置
- `frontend/src/views/` — Dashboard 页面
- `deploy/` — Dockerfile、Compose、Worker 启动脚本

## Dashboard 一览

| 页面 | 用途 |
|------|------|
| **工作区** | |
| 仪表盘 | 概览、热力图、趋势 |
| 需求 | 需求列表与详情 |
| &ensp;↳ 创建需求 | 用提示词模板快速描述需求 |
| 任务 | 任务列表与详情，含实时日志 |
| &ensp;↳ 创建任务 | 手动配置并发起任务 |
| 会话管理 | 查看和管理登录会话 |
| **洞察** | |
| 统计分析 | 执行趋势与成功率 |
| 调度总览 | 查看队列和调度状态 |
| 监控 | 运行时状态与健康检查 |
| **管理** | |
| 访问管理 | 用户与权限 |
| 系统配置 | 运行时参数和集成配置 |
| &ensp;↳ OIDC 诊断 | 调试 SSO 登录问题 |

## 快速开始

### 你需要

- Docker 与 Docker Compose
- 一个可访问的 GitLab 实例
- 一个兼容 Claude CLI 的模型服务端点

### 1. 填写配置

`deploy/docker-compose.yml` 默认从 `deploy/.env.test` 读取环境变量，至少填好这几项：

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `ANTHROPIC_API_KEY`

小贴士：

- 运行时覆盖配置会持久化到 PostgreSQL 的 `system_config`
- 在 Dashboard 中录入的敏感配置会加密存储
- 如果 PostgreSQL volume 被删除，运行时配置、用户、会话和认证状态都会丢失

### 2. 一键启动

```bash
cd deploy
docker-compose up -d --build
```

默认端口：

- 前端：`http://localhost:8880`
- 后端 API：`http://localhost:8000`

### 3. 配置登录（推荐）

首次部署建议先跳过 OIDC，跑通基本流程后再开启。详见 [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)。

推荐步骤：

1. 先保持 OIDC 关闭，确认服务正常运行
2. 确保 `CONFIG_ENCRYPTION_KEY` 已设置
3. 在 Dashboard → 系统配置 页面填写 OIDC 参数
4. 验证通过后再启用

## 常用命令

运行 `make help` 查看所有可用命令。

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
docker build -f deploy/Dockerfile.backend -t codify-backend:latest .
cd deploy && docker-compose up -d backend scheduler

# frontend / nginx
docker build -f deploy/Dockerfile.frontend -t codify-nginx:latest .
cd deploy && docker-compose up -d --build nginx

# worker
docker build -f deploy/Dockerfile.worker -t codify-worker:latest .
```

## 使用方式

在 Dashboard 里走完三步即可：

1. **写需求** — 说明要解决的问题、期望结果和限制条件
2. **发起任务** — 可以立即运行，也可以排到指定时间
3. **查看结果** — 在仪表盘跟踪状态、翻阅日志、检查交付物

## 运维备忘

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
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)
- [e2e-debugging.md](e2e-debugging.md)
- [../deploy/offline-bundle/README.md](../deploy/offline-bundle/README.md)

## License

MIT
