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
# 完整流程（启动环境 → 并行 + 串行 → 关闭环境）
make test-e2e

# 仅并行测试（116 个，~44s）
make test-e2e-parallel

# 仅串行测试（bootstrap/prompt_template/access_management，~42s）
make test-e2e-serial

# 运行特定测试文件
make test-e2e-specific TEST_FILE=test_dashboard.py

# 分步控制
make test-e2e-up      # 启动测试环境（自动构建镜像）
make test-e2e-down    # 关闭测试环境
```

> **注意**：`pytest.ini` 默认启用 `-n auto --dist=loadfile`；状态相关测试（bootstrap/prompt_template/access_management）在 xdist worker 中自动跳过，须用 `test-e2e-serial` 单独运行

### 测试分组说明

| 分组 | 文件 | 测试数 | 运行方式 |
|------|------|--------|---------|
| 并行（无状态） | `test_create_task`, `test_dashboard`, `test_manual_task`, `test_navigation`, `test_task_details`, `test_task_queue`, `test_task_view` | 116 | `make test-e2e-run` |
| 串行（有状态） | `test_bootstrap`, `test_prompt_template`, `test_access_management` | 18+2 | `--override-ini` 串行运行 |

### 并行架构设计

```
pytest -n auto --dist=loadfile
      │
      ├─ gw0 ── test_dashboard.py ──── test_admin_gw0 用户
      ├─ gw1 ── test_navigation.py ─── test_admin_gw1 用户
      ├─ gw2 ── test_create_task.py ── test_admin_gw2 用户
      └─ gw3 ── test_task_view.py ──── test_admin_gw3 用户
```

**关键机制：**

| 组件 | 串行模式 | 并行（xdist）模式 |
|------|---------|----------------|
| 管理员用户 | `test_admin`（每次测试重新注册） | `test_admin_gw0/gw1/…`（session 级别，各 worker 独立） |
| 用户创建方式 | `POST /api/auth/local/register` | 直接 INSERT DB（绕过 API 竞态） |
| 密码 Hash | 600,000 次 PBKDF2 | 1 次 PBKDF2（快速；backend 从 hash 字符串读取迭代次数） |
| `reset_database` | 清空全部 users + sessions + 重置 bootstrap | 仅删除**本 worker** 的 sessions（不碰其他 worker 的用户） |
| `_api_login` | register→fallback login | 直接 `/login`（system 已初始化） |
| `PYTEST_XDIST_WORKER` | 未设置 | 设置为 `gw0`, `gw1`, … |

**串行组自动跳过：** `test_bootstrap.py`、`test_prompt_template.py`、`test_access_management.py` 顶部有：
```python
pytestmark = pytest.mark.skipif(
    bool(os.environ.get("PYTEST_XDIST_WORKER")),
    reason="Requires serial execution (modifies shared DB state)"
)
```
这些测试在 xdist worker 中自动跳过，需单独用 `make test-e2e-serial` 运行。

### 编写新测试用例的规则

#### 1. 先判断分组——并行 or 串行？

**可以并行**（放入现有并行文件或新建并行文件）：
- 只读取页面 UI 元素（导航、布局、静态内容）
- 不创建/修改数据库记录
- 不依赖 `system_bootstrap.initialized` 的值

**必须串行**（放入或新建带 `pytestmark skipif` 的文件）：
- 修改 `system_bootstrap`（bootstrap 流程测试）
- 在共享表中创建/删除命名记录（如 prompt_templates）
- 修改其他用户的角色或权限
- 依赖数据库中只有一个用户的假设

新建串行测试文件时，在文件顶部添加：
```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    bool(os.environ.get("PYTEST_XDIST_WORKER")),
    reason="Requires serial execution (modifies shared DB state)"
)
```
并将该文件加入串行运行命令中。

#### 2. 使用 `logged_in_page` 而非手动登录

```python
# ✅ 正确：使用 fixture，自动处理 xdist 和串行两种模式
def test_something(self, logged_in_page: Page, reset_database):
    logged_in_page.goto("/dashboard")
    ...

# ❌ 错误：手动调用 bootstrap UI 或 login 页面
def test_something(self, page: Page):
    page.goto("/bootstrap")  # 不要这样做
    ...
```

#### 3. 用确定性等待，不用 `wait_for_timeout`

```python
# ✅ 正确：等待具体元素或状态
page.wait_for_selector(".my-component", state="visible", timeout=10000)
page.wait_for_load_state("networkidle")
expect(page.get_by_role("button", name="Save")).to_be_visible()

# ❌ 错误：硬编码延迟
page.wait_for_timeout(2000)
```

#### 4. Naive UI 组件的选择器规则

Naive UI 的 `n-button`、`n-input` 等**不会**将 `data-testid` 透传到底层 DOM 元素：

```python
# ✅ 正确
page.get_by_role("button", name="Create Template")
page.locator(".my-panel input").first
page.locator(".my-panel").get_by_role("button", name="Delete")

# ❌ 错误（data-testid 不会出现在 DOM 中）
page.get_by_test_id("create-button")   # n-button 不透传
page.get_by_test_id("name-input")      # n-input 不透传
```

`n-popconfirm` 的确认按钮渲染在 body 级别的 portal 中，不在触发元素旁边：
```python
# ✅ 正确：从 body 级 portal 查找
page.locator(".n-popover").get_by_role("button", name="Delete").click()
```

#### 5. 配置页面的 Tab 导航

```python
# ✅ 正确：通过 URL query 参数导航并等待 networkidle
page.goto("/configuration?tab=prompt-templates")
page.wait_for_load_state("networkidle")

# ❌ 不稳定：直接点击 tab 而不等待内容加载
page.get_by_role("tab", name="Prompt Templates").click()
# 点击后可能需要等待 API 响应完成
```

### 运行特定测试

```bash
# 运行特定测试文件
make test-e2e-specific TEST_FILE=test_dashboard.py

# 运行特定测试文件（含视频录制）
make test-e2e-specific TEST_FILE=test_dashboard.py RECORD=1

# 运行特定测试方法（直接调用 docker-compose，需已 up）
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py::TestDashboardPage::test_dashboard_page_loads

# 按标记运行
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

### 视频录制

在任意测试命令后加 `RECORD=1` 即可开启录制：

```bash
make test-e2e RECORD=1                              # 录制全套测试
make test-e2e-parallel RECORD=1                     # 仅录制并行测试
make test-e2e-serial RECORD=1                       # 仅录制串行测试
make test-e2e-specific TEST_FILE=test_dashboard.py RECORD=1  # 录制指定文件
```

视频文件保存到 `deploy/e2e-videos/`，命名格式：`<test_name>_<worker_id>.webm`，例如：
```
test_dashboard_page_loads_chromium_gw0.webm
```

> **注意**：
> - 视频录制仅对使用 `logged_in_page` fixture 的测试生效
> - 录制会增加约 20-30% 的运行时间
> - 视频存储在容器内 `/videos/`，通过 `docker cp` 自动提取到本地（兼容远程 Docker daemon）
> - `deploy/e2e-videos/*.webm` 已加入 `.gitignore`，不会提交到仓库

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
