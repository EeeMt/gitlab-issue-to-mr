# 测试指南

本文档介绍项目中所有类型测试的运行方法。

## 快速开始

所有测试命令统一通过 `make` 运行：

```bash
# 查看所有可用测试命令
make help

# 运行所有单元测试（推荐开发时使用）
make test-unit

# 运行所有测试（包括 E2E）
make test-all
```

## 测试类型概览

| 类型 | 命令 | 依赖 |
|------|------|------|
| 后端单元测试 | `make test-backend` | Python |
| 前端单元测试 | `make test-frontend` | Node.js |
| Mock E2E | `make test-mock-e2e` | Python |
| Mock 集成测试 | `make test-mock-integration` | Docker |
| Playwright E2E | `make test-e2e-ui` | Docker |
| GitLab E2E | `make test-e2e-gitlab` | Docker + 真实 GitLab |
| 全部 E2E | `make test-e2e` | Docker（含 GitLab） |

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
- 使用 `pytest` + `asyncio_mode = "auto"` 异步测试
- 大量使用 mock 避免外部依赖
- 运行快速（通常 < 30 秒，约 408 个测试）

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

## 4. Mock 集成测试

Mock 集成测试用 Mock 服务替代外部依赖（GitLab API、Claude CLI），但保留真实 Docker 容器、真实 entrypoint.sh（683行）、真实业务逻辑。与纯 Mock E2E 不同，这套测试在完整的 Docker 容器环境中运行。

### 架构

```
pytest (本机) → HTTP → codify-backend (Docker)
                      → codify-scheduler (Docker)
                      → mock-services (Docker): Mock GitLab API + Git HTTP + Anthropic API
                      → codify-worker-test (Docker): 真实 entrypoint.sh + fake ci-claude.sh
                      → postgres (Docker)
```

### 运行命令

```bash
make test-mock-integration          # 一键运行（构建+启动+测试）
make test-mock-integration-up       # 仅启动环境
cd backend && pytest tests/mock_integration/ -v  # 手动运行测试
make test-mock-integration-down     # 停止环境
```

### 测试文件概览（19 文件，222 个测试）

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| test_happy_path.py | 4 | 核心 task→MR 流程 |
| test_entrypoint.py | 11 | entrypoint.sh 逻辑 |
| test_failure_paths.py | 3 | Claude 失败、超时、取消 |
| test_edge_cases.py | 7 | 边缘场景 |
| test_scheduling.py | 2 | 优先级、并发 |
| test_advanced.py | 6 | Base branch、mutex、crash recovery |
| test_additional.py | 8 | 超时、验证 |
| test_gap_analysis.py | 7 | No-changes、MR 失败、并发 |
| test_coverage_gaps.py | 9 | 事件过滤、CODIFY markers |
| test_api_endpoints.py | 12 | 分页、SSE、重试、日志 |
| test_system_apis.py | 14 | 统计、分析、配置、认证 |
| test_admin_and_templates.py | 13 | 模板、用户管理、会话 |
| test_webhook_and_lifecycle.py | 14 | 提示词、运行时配置、生命周期 || test_notifications_and_operations.py | 17 | 通知、slot capacity |
| test_mr_followup_and_env.py | 12 | MR follow-up、容器环境、重试 |
| test_health_access_sse.py | 25 | 健康检查、访问控制、SSE |
| test_remaining_endpoints.py | 27 | 剩余端点覆盖 |
| test_failure_injection.py | 15 | 故障注入（项目404、退出码、git clone、组合故障） |
| test_mutex_and_scheduling.py | 16 | 互斥锁、调度、分支验证、快速创建 |

### 关键配置

| 配置项 | 值 |
|--------|-----|
| WORKER_NETWORK | codify-mock-test |
| MAX_CONCURRENCY | 2 |
| TASK_TIMEOUT | 120 |
| Backend 端口 | 18000 |
| Mock 服务端口 | 19000 |

> **注意**：完整运行约 17 分钟，可单独运行文件加快调试：
> ```bash
> cd backend && pytest tests/mock_integration/test_happy_path.py -v
> ```

---

## 5. Playwright E2E 测试

Playwright E2E 测试需要完整的 Docker 环境。测试套件用 **pytest-xdist 并行执行**（状态无关测试并行，状态相关测试串行）。

### 运行命令

```bash
# 完整流程（启动环境 → 并行 + 串行 → 关闭环境）
make test-e2e

# 仅并行测试（214 个，~73s）
make test-e2e-parallel

# 仅串行测试（bootstrap/prompt_template/access_management，~39s）
make test-e2e-serial

# 运行特定测试文件
make test-e2e-specific TEST_FILE=test_dashboard.py

# 分步控制
make test-e2e-up      # 启动测试环境（自动构建镜像）
make test-e2e-down    # 关闭测试环境
make test-e2e-logs    # 查看测试环境日志

# 带视频录制（视频保存到 deploy/e2e-videos/，已 .gitignore，仅对使用 logged_in_page 的测试生效）
make test-e2e RECORD_VIDEO=1
```

### 测试分组说明

| 分组 | 文件 | 测试数 | 运行方式 |
|------|------|--------|---------|
| 并行（无状态） | `test_create_task`, `test_dashboard`, `test_manual_task`, `test_navigation`, `test_task_details`, `test_task_queue`, `test_task_view`, `test_shell`, `test_monitor`, `test_analytics`, `test_config_tabs`, `test_sessions`, `test_schedule_overview`, `test_oidc_diagnostics` | 214 | `make test-e2e-parallel` |
| 串行（有状态） | `test_bootstrap`, `test_prompt_template`, `test_access_management` | 20 | `make test-e2e-serial` |

> `pytest.ini` 默认启用 `-n auto --dist=loadfile`；串行文件带 `pytestmark = skipif(PYTEST_XDIST_WORKER)` 在并行 worker 中自动跳过。

### 环境说明
- E2E 测试环境使用 `18980` 端口，避免与开发环境 `8880` 冲突
- 使用独立的 PostgreSQL（tmpfs，无持久化）

> 编写测试的规则（并行/串行分组判断、`logged_in_page`、确定性等待、Naive UI 选择器）与
> 并行架构细节见 [E2E_TESTS.md](./E2E_TESTS.md)。

---

## 6. GitLab E2E 测试

### 运行命令

```bash
# 需先启动 E2E 环境
make test-e2e-up

# 运行 GitLab E2E 测试（在 Docker 容器内执行）
make test-e2e-gitlab
```

### 测试文件

| 文件 | 说明 | 依赖 |
|------|------|------|
| `test_manual_task.py` | 手动任务创建 (GitLab API) | 真实 GitLab |
| `test_integration.py` | 集成流程 | 真实 GitLab |
| `test_task_execution.py` | 任务创建 API + 执行完整流程 | 见下表 |

#### `test_task_execution.py` 各测试类依赖

| 测试类 | 说明 | 运行环境 |
|--------|------|---------|
| `TestTaskAPIIntegrity` | 快速 API 完整性检查（6个，< 3s）| E2E 环境 |
| `TestManualTaskExecution` | 完整 worker 执行（需 Claude CLI）| 真实部署（有 GitLab + Claude） |
| `TestScheduledTaskExecution` | 调度行为验证（需 Claude CLI）| 真实部署（有 GitLab + Claude） |

#### 运行 TestTaskAPIIntegrity（推荐使用 E2E 环境）

```bash
# 先启动 E2E 环境
make test-e2e-up

# 在 Docker 容器内运行特定测试
make test-e2e-specific TEST_FILE=../gitlab_e2e/test_task_execution.py::TestTaskAPIIntegrity
```

> **认证说明**：`test_task_execution.py` 自动处理认证：
> - 系统未初始化时（E2E 新鲜环境）：自动注册 `test_admin_gitlab_e2e` 用户（密码 `SecurePass123!`）
> - 系统已初始化时（dev 环境）：尝试登录，若失败则 skip（不报错）

#### 运行完整执行测试（需真实 GitLab + Claude CLI）

```bash
# 确保 deploy/.env.test 中已配置：
# GITLAB_URL, GITLAB_BOT_TOKEN, ANTHROPIC_API_KEY, ANTHROPIC_MODEL 等
make test-e2e-up
make test-e2e-gitlab
```

### 环境要求
- 可访问的 GitLab 实例（`test_task_execution.py::TestTaskAPIIntegrity` 不需要）
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

- [E2E_TESTS.md](./E2E_TESTS.md) - Playwright E2E 测试详细指南（含集成调试与 GitLab 验证）
