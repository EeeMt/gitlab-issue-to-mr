# 测试指南

本文档介绍项目中所有类型测试的运行方法。

## 快速开始

所有测试命令统一通过 `make` 运行：

```bash
# 查看所有可用测试命令
make help

# 运行所有单元测试（推荐开发时使用）
make test

# 运行所有测试（包括 E2E）
make test-all
```

## 测试类型概览

| 类型 | 命令 | 依赖 |
|------|------|------|
| 后端单元测试 | `make test-backend` | Python |
| 前端单元测试 | `make test-frontend` | Node.js |
| Mock E2E | `make test-mock-e2e` | Python |
| GitLab E2E | `make test-gitlab-e2e` | Python + 真实 GitLab |
| Playwright E2E | `make test-e2e` | Docker |

---

## 1. 后端单元测试

### 运行命令

```bash
make test-backend
```

或直接使用 pytest：

```bash
cd backend
source .venv/bin/activate  # Linux/Mac
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

---

## 2. 前端单元测试

### 运行命令

```bash
make test-frontend
```

或直接使用 vitest：

```bash
cd frontend
npx vitest run

# 带 watch 模式
npx vitest

# 生成覆盖率报告
npx vitest run --coverage
```

### 特点
- 使用 Vitest + Vue Test Utils
- 测试文件命名：`*.spec.ts` 或 `*.test.ts`

---

## 3. Mock E2E 测试

### 运行命令

```bash
make test-mock-e2e
```

### 特点
- 不需要 Docker 或外部服务
- 使用 mock 模拟 GitLab API 响应
- 适合验证核心业务流程

---

## 4. Playwright E2E 测试

Playwright E2E 测试需要完整的 Docker 环境。测试套件使用 **pytest-xdist 并行执行**，运行时间约 44 秒（状态无关测试并行）+ 42 秒（状态相关测试串行）。

### 运行命令

```bash
# 完整流程（启动环境 -> 运行测试 -> 清理）
make test-e2e

# 或分步执行
make test-e2e-up      # 启动测试环境
make test-e2e-run     # 运行并行测试（116 个，~44s，默认 -n auto）
make test-e2e-down    # 清理环境

# 串行运行状态相关测试（bootstrap/prompt_template/access_management，~42s）
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest \
  tests/e2e/tests/test_bootstrap.py \
  tests/e2e/tests/test_prompt_template.py \
  tests/e2e/tests/test_access_management.py \
  --override-ini="addopts=-v --tb=short --strict-markers --disable-warnings"
```

> **注意**：
> - 测试环境使用 `18980` 端口，避免与开发环境 `8880` 冲突
> - `pytest.ini` 默认启用 `-n auto --dist=loadfile`；状态相关测试在 xdist worker 中自动跳过，须用上方串行命令单独运行

### 测试分组说明

| 分组 | 文件 | 测试数 | 运行方式 |
|------|------|--------|---------|
| 并行（无状态） | `test_create_task`, `test_dashboard`, `test_manual_task`, `test_navigation`, `test_task_details`, `test_task_queue`, `test_task_view` | 116 | `make test-e2e-run` |
| 串行（有状态） | `test_bootstrap`, `test_prompt_template`, `test_access_management` | 18+2 | `--override-ini` 串行运行 |

### 运行特定测试

```bash
# 运行特定测试文件
make test-e2e-specific TEST_FILE=test_dashboard.py

# 运行特定测试方法
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py::TestDashboardPage::test_dashboard_page_loads

# 按标记运行（如只运行 dashboard 相关测试）
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest -m dashboard -v
```

### 调试选项

```bash
# 带可见浏览器运行
make test-e2e-up
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v --headed

# 查看日志
make test-e2e-logs
```

### 环境说明
- E2E 测试环境使用 `18980` 端口，避免与开发环境 `8880` 冲突
- 使用独立的 PostgreSQL（tmpfs，无持久化）

---

## 5. GitLab E2E 测试

### 运行命令

```bash
make test-gitlab-e2e
```

### 环境要求
- 可访问的 GitLab 实例
- 有效的 `GITLAB_BOT_TOKEN`
- 测试项目和配置（在 `deploy/.env.test` 中）

### 安全注意事项

> **警告**：真实 GitLab E2E 测试只应该跑在隔离测试环境。

- 测试可能创建任务、分支、MR、Issue 评论
- 不要对着正式环境运行

---

## 重建镜像

代码修改后，E2E 环境会自动使用 `--build` 重建：

```bash
make test-e2e-up  # 会自动重建镜像
```

---

## 相关文档

- [E2E_TESTS.md](./E2E_TESTS.md) - Playwright E2E 测试详细指南
- [e2e-debugging.md](./e2e-debugging.md) - E2E 测试调试指南
