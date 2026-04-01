# 测试指南

本文档介绍项目中所有类型测试的运行方法。

## 测试类型概览

| 类型 | 位置 | 运行方式 | 依赖 |
|------|------|----------|------|
| 后端单元测试 | `backend/tests/unit/` | pytest | 无外部依赖 |
| 前端单元测试 | `frontend/src/` | vitest | 无外部依赖 |
| Mock E2E | `backend/tests/mock_e2e/` | pytest | 无外部依赖 |
| Playwright E2E | `backend/tests/e2e/` | pytest + Playwright | Docker 服务 |
| GitLab E2E | `backend/tests/gitlab_e2e/` | pytest + Python | 真实 GitLab |

---

## 1. 后端单元测试

### 运行命令

```bash
# 进入 backend 目录
cd backend

# 如果没有虚拟环境，需要先创建并安装依赖
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或: .\.venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt

# 运行所有单元测试
python -m pytest tests/unit/ -v

# 运行特定测试文件
python -m pytest tests/unit/test_auth_session.py -v

# 运行特定测试类
python -m pytest tests/unit/test_auth_session.py::AuthSessionTests -v
```

### 特点
- 使用 `unittest.IsolatedAsyncioTestCase` 异步测试
- 大量使用 mock 避免外部依赖
- 运行快速（通常 < 2 秒）

### 依赖
- Python 3.11+
- 已安装 `requirements.txt` 中的所有依赖

---

## 2. 前端单元测试

### 运行命令

```bash
# 进入 frontend 目录
cd frontend

# 安装依赖
npm install

# 运行所有前端测试
npx vitest run

# 运行测试（带 watch 模式）
npx vitest

# 生成覆盖率报告
npx vitest run --coverage
```

### 特点
- 使用 Vitest + Vue Test Utils
- 测试文件命名：`*.spec.ts` 或 `*.test.ts`
- 位于 `frontend/src/` 各模块目录下

### 依赖
- Node.js 18+
- npm

---

## 3. Mock E2E 测试

### 运行命令

```bash
cd backend
source .venv/bin/activate  # 或 .\venv\Scripts\Activate.ps1 (Windows)

# 运行所有 Mock E2E 测试
python -m pytest tests/mock_e2e/ -v

# 运行特定测试文件
python -m pytest tests/mock_e2e/test_manual_task.py -v
```

### 特点
- 不需要 Docker 或外部服务
- 使用 mock 模拟 GitLab API 响应
- 适合验证核心业务流程

### 依赖
- Python 3.11+
- 已安装 `requirements.txt`

---

## 4. Playwright E2E 测试

Playwright E2E 测试需要完整的 Docker 环境。

### 快速开始

```bash
# 1. 启动测试环境
cd deploy
docker-compose -f docker-compose.e2e.yml up -d

# 2. 运行所有 E2E 测试
docker-compose -f docker-compose.e2e.yml run --rm e2e

# 3. 清理环境
docker-compose -f docker-compose.e2e.yml down
```

### 运行特定测试

```bash
# 运行特定测试文件
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v

# 运行特定测试类
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py::TestDashboardPage -v

# 运行特定测试方法
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py::TestDashboardPage::test_dashboard_page_loads -v

# 按标记运行（如只运行 dashboard 相关测试）
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest -m dashboard -v
```

### 调试选项

```bash
# 带可见浏览器运行
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v --headed

# 生成 HTML 报告
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/ -v --html=report.html --self-contained-html

# 复制报告到本地
docker cp <container_id>:/app/report.html ./
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `E2E_BASE_URL` | `http://nginx:80` | 前端 Nginx 地址 |
| `E2E_BACKEND_URL` | `http://backend:8000` | 后端 API 地址 |
| `E2E_GITLAB_URL` | `http://gitlab:8080` | GitLab 地址 |
| `E2E_POSTGRES_URL` | `postgresql://...` | PostgreSQL 数据库地址 |

### 重建镜像

代码修改后需要重建镜像：

```bash
# 重建 backend 镜像
docker build -f deploy/Dockerfile.backend -t gimr-backend:latest ..

# 重建 frontend 镜像
docker build -f deploy/Dockerfile.frontend -t gimr-nginx:latest ..

# 重启服务
docker-compose -f docker-compose.e2e.yml up -d backend nginx
```

### 本地运行（不使用 Docker）

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt
pip install -r tests/e2e/requirements-e2e.txt
playwright install chromium

# 2. 启动后端服务
# （需要有 PostgreSQL 运行）

# 3. 运行测试
pytest tests/e2e/ -v
```

详细文档：[E2E_TESTS.md](./E2E_TESTS.md)

---

## 5. GitLab E2E 测试

GitLab E2E 测试需要真实的 GitLab 环境。

### 运行命令

```bash
cd backend
source .venv/bin/activate  # 或 .\venv\Scripts\Activate.ps1 (Windows)

# 运行所有 GitLab E2E 测试
python -m pytest tests/gitlab_e2e/ -v

# 运行特定测试
python -m pytest tests/gitlab_e2e/test_manual_task.py -v

# 运行集成测试
python tests/gitlab_e2e/test_integration.py --skip-startup
```

### 环境要求

- 可访问的 GitLab 实例
- 有效的 `GITLAB_BOT_TOKEN`
- 测试项目和配置（在 `deploy/.env.test` 中）

### 安全注意事项

> **警告**：真实 GitLab E2E 测试只应该跑在隔离测试环境。

- 测试可能创建任务、分支、MR、Issue 评论
- 不要对着正式环境运行
- 确保测试环境有适当的清理机制

详细文档：[e2e-debugging.md](./e2e-debugging.md)

---

## 快速参考

### 本地开发推荐流程

```bash
# 1. 修改代码
# ...

# 2. 运行后端单元测试验证
cd backend
source .venv/bin/activate  # 或 .\venv\Scripts\Activate.ps1 (Windows)
python -m pytest tests/unit/ -v

# 3. 运行前端单元测试
cd frontend && npx vitest run

# 4. 如果需要，运行 Mock E2E
cd backend && python -m pytest tests/mock_e2e/ -v

# 5. 如果需要完整验证，运行 Playwright E2E
cd deploy && docker-compose -f docker-compose.e2e.yml up -d
docker-compose -f docker-compose.e2e.yml run --rm e2e
```

### 常用测试命令速查

| 命令 | 说明 |
|------|------|
| `cd backend && source .venv/bin/activate && python -m pytest tests/unit/ -v` | 后端单元测试 |
| `cd frontend && npx vitest run` | 前端单元测试 |
| `cd backend && source .venv/bin/activate && python -m pytest tests/mock_e2e/ -v` | Mock E2E |
| `cd deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e` | Playwright E2E |
| `cd backend && source .venv/bin/activate && python -m pytest tests/gitlab_e2e/ -v` | GitLab E2E |

> **注意**：后端测试需要先激活虚拟环境 `source .venv/bin/activate`（或 Windows 上 `.\.venv\Scripts\Activate.ps1`）。

---

## 相关文档

- [E2E_TESTS.md](./E2E_TESTS.md) - Playwright E2E 测试详细指南
- [e2e-debugging.md](./e2e-debugging.md) - E2E 测试调试指南
- [DEVELOPMENT.md](./DEVELOPMENT.md) - 开发环境搭建
