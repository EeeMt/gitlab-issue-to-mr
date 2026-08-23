# 开发环境搭建指南

本文档面向本地开发者，介绍如何搭建 Codify 的后端、前端和测试环境，并说明推荐的开发流程。

## 1. 你会开发到哪些部分

当前仓库主要由三部分组成：

- `backend/`：FastAPI + SQLAlchemy + 调度与任务执行逻辑
- `frontend/`：Vue 3 + Vite + Naive UI 的管理后台
- `deploy/`：Docker Compose 与生产/集成部署相关文件

日常开发通常分两类：

- 本地开发后端 / 前端，快速迭代
- 通过 Docker 或远程 Docker 环境验证完整链路

## 2. 前置条件

建议本地具备以下工具：

- Python 3.11 或兼容版本
- Node.js 18+ 与 npm
- Docker 与 Docker Compose
- PostgreSQL（本地安装，或通过 Docker 提供）
- 可访问的 GitLab 测试环境
- 可访问的 Harness 兼容模型服务（Claude/Codex）

如果你要跑真实 GitLab E2E，还需要：

- 独立测试项目
- 独立测试 Token
- 不会影响正式环境的数据隔离

## 3. 获取代码

```bash
git clone <your-repo-url>
cd codify
```

## 4. 后端开发环境

### 4.1 安装 Python 依赖

```bash
cd backend
pip install -r requirements.txt
```

如果你使用虚拟环境，建议先创建并激活虚拟环境再安装。

### 4.2 准备环境变量

从模板复制：

```bash
cp .env.example .env
```

然后按本地环境修改关键项：

#### GitLab

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`

#### 模型服务

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`

#### 数据库

- `DATABASE_URL`

注意：

- `.env.example` 中的数据库地址默认面向 Docker 网络里的 `postgres`
- 如果你是在宿主机直接运行后端，需要把 `DATABASE_URL` 改成你本机可访问的 PostgreSQL 地址

#### 应用配置

- `SECRET_KEY`
- `WORKER_IMAGE`
- `MAX_CONCURRENCY`
- `TASK_TIMEOUT`
- `DEFAULT_TARGET_BRANCH`

### 4.3 准备 PostgreSQL

你可以任选一种方式：

#### 方式 A：本机已有 PostgreSQL

手动创建数据库并把 `DATABASE_URL` 指向本机数据库。

#### 方式 B：用 Docker 起一个 PostgreSQL

最简单的方式是直接使用项目里的 compose，把 `codify-postgres` 起起来：

```bash
cd ../deploy
docker-compose up -d
# 或只启动 postgres：docker-compose up -d codify-postgres
```

然后在 `backend/.env` 中把 `DATABASE_URL` 指向与当前运行方式匹配的地址。

如果后端也跑在宿主机上，通常不能直接使用 `postgres:5432` 这个容器内主机名，需改成宿主机可访问地址。

### 4.4 执行数据库迁移

Backend 与 Scheduler 默认都不自动迁移（`AUTO_MIGRATE=false`）。开发环境应先显式执行迁移，再启动
长驻服务；生产/Canary 必须使用评审后的精确 revision，不能让多个服务竞争执行：

```bash
# 方式一：后端本地运行时（在 backend/ 目录，有 Python 环境）
cd backend
python -m alembic upgrade head

# 方式二：后端在 Docker 中运行时
MIGRATION_TARGET=<reviewed_revision> docker compose --profile maintenance run --rm migrate
```

> 项目使用 Alembic 进行数据库迁移，迁移脚本位于 `backend/alembic/versions/`。

### 4.5 本地启动后端

```bash
HARNESS_EXECUTION_MODE=dual_canary uvicorn app.main:app --reload
```

默认后端地址通常是：

- `http://localhost:8000`

## 5. 前端开发环境

### 5.1 安装依赖

```bash
cd frontend
npm install
```

### 5.2 启动开发服务器

```bash
npm run dev
```

前端开发服务器启动后，通常会提供一个本地端口，例如 `http://localhost:5173`。

### 5.3 前端构建校验

前端改动完成后，推荐执行：

```bash
npm run build
```

这也是当前仓库里最直接的前端类型/构建校验方式。

## 6. 推荐本地开发组合

### 方案 A：前后端都本地运行

适合前端页面与后端 API 联调。

推荐组合：

- PostgreSQL：本地或 Docker
- backend：宿主机 `uvicorn --reload`
- frontend：宿主机 `npm run dev`

优点：

- 改动反馈最快
- 日志查看最直接
- 调试工具最方便

### 方案 B：前端本地，后端使用远端或 Docker 环境

适合你只改前端、希望直接对接现有测试后端。

注意确认前端 API 指向和跨域设置是否匹配当前环境。

### 方案 C：用 compose 验证接近生产的运行方式

适合验证部署问题、容器行为和调度问题：

```bash
cd deploy
docker-compose up -d --build
```

这个方案更接近生产，但迭代速度比本地直接跑慢。

## 7. 常用开发命令

### 7.1 后端

```bash
# 安装依赖
cd backend && pip install -r requirements.txt

# 本地运行
cd backend && uvicorn app.main:app --reload

# 手动迁移
cd backend && alembic upgrade head
```

### 7.2 前端

```bash
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run build
```

### 7.3 Docker / 部署验证

```bash
cd deploy && docker-compose up -d --build
cd deploy && docker-compose logs -f
```

## 8. 测试

详细测试指南请参阅：[TESTING.md](TESTING.md)

### 快速参考

| 测试类型 | 命令 |
|---------|------|
| 后端单元测试 | `cd backend && python -m pytest tests/unit/ -v` |
| 前端单元测试 | `cd frontend && npx vitest run` |
| Mock E2E | `cd backend && python -m pytest tests/mock_e2e/ -v` |
| Playwright E2E | `cd deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e` |

### 前端验证

```bash
cd frontend && npm run build
```

### 安全注意事项

> **警告**：真实 GitLab E2E 测试只应该跑在隔离测试环境。

- 测试可能创建任务、分支、MR、Issue 评论
- 不要对着正式环境运行
- 确保测试环境有适当的清理机制

## 9. 本地开发常见问题

### 9.1 后端启动时报数据库连接失败

先确认：

- PostgreSQL 是否真的已启动
- `DATABASE_URL` 是否指向当前运行方式下可访问的地址
- 你是否误用了 Docker 内部主机名 `postgres`

### 9.2 前端页面打开了，但接口全 401 或无数据

先确认：

- 当前环境是否启用了 OIDC
- 你是否已经登录
- 后端 `/api/auth/me` 返回的 `oidc_enabled` 和 `authenticated` 是否符合预期

### 9.3 任务能创建，但 Worker 起不来

先确认：

- `DOCKER_HOST` 是否可用
- `WORKER_IMAGE` 是否存在
- 当前运行方式能否访问 Docker Engine

### 9.4 OIDC UI 元素突然消失

先确认：

- 数据库里的 `system_config` 是否还在
- OIDC 配置是否因数据库重置而丢失
- `/api/config` 与 `/api/auth/me` 返回值是否正常

## 10. 推荐开发流程

比较稳妥的日常流程如下：

1. 拉取最新代码
2. 本地修改后端或前端
3. 先跑与你改动最相关的测试
4. 前端改动至少执行一次 `cd frontend && npm run build`
5. 后端行为改动至少跑对应单元测试 / E2E
6. 需要接近生产验证时，再用 compose 或远程 Docker 环境复测

## 11. 相关文档

- [文档索引](README.md)
- [项目总览 README](../README.md)
- [README.zh-CN.md](README.zh-CN.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)
- [E2E_TESTS.md](E2E_TESTS.md)
