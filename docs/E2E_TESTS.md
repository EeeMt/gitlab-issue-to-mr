# E2E 测试指南

本文档介绍 Codify 项目的 Playwright E2E 浏览器测试的开发、运行、调试方法，以及真实 GitLab 集成测试的排查要点。合并自原 `E2E_TESTS.md` 与 `e2e-debugging.md`。

## 目录

- [快速开始](#快速开始)
- [环境配置](#环境配置)
- [运行测试](#运行测试)
- [并行 / 串行架构](#并行--串行架构)
- [测试结构](#测试结构)
- [编写测试](#编写测试)
- [Fixtures 详解](#fixtures-详解)
- [常见问题](#常见问题)
- [调试技巧](#调试技巧)
- [调试命令速查](#调试命令速查)
- [GitLab 集成验证](#gitlab-集成验证)

---

## 快速开始

### 启动测试环境并运行所有测试

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

> 更完整的运行方式（并行/串行分组、视频录制、单文件运行）见 [TESTING.md](TESTING.md)。

---

## 环境配置

### 文件结构

```
deploy/
├── docker-compose.e2e.yml    # E2E 测试环境配置
├── Dockerfile.e2e            # E2E 测试容器构建
├── Dockerfile.backend        # Backend 镜像
└── Dockerfile.frontend      # Frontend 镜像

backend/tests/e2e/
├── conftest.py              # Pytest fixtures 和配置
├── requirements-e2e.txt     # E2E 测试依赖
└── tests/
    ├── test_bootstrap.py        # Bootstrap 页面测试
    ├── test_dashboard.py        # 仪表盘测试
    ├── test_create_task.py      # 创建任务页面测试
    ├── test_task_view.py       # 任务详情页测试
    ├── test_task_details.py    # 任务详情组件测试
    ├── test_task_queue.py      # 任务队列测试
    ├── test_manual_task.py     # 手动任务测试
    ├── test_prompt_template.py # Prompt 模板测试
    ├── test_access_management.py # 访问管理测试
    ├── test_navigation.py      # 导航测试
    └── test_debug_bootstrap.py # Bootstrap 调试测试
```

### docker-compose.e2e.yml 配置

```yaml
services:
  postgres:
    image: postgres:16-alpine
    # 使用 tmpfs 存储，测试后数据不持久化

  backend:
    image: codify-backend:latest
    environment:
      - DATABASE_URL=postgresql+asyncpg://codify:codify_password@postgres:5432/codify
      - AUTO_MIGRATE=true

  nginx:
    image: codify-nginx:latest

  e2e:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.e2e
    command: pytest tests/e2e/tests/ -v  # 默认运行所有测试
    environment:
      - E2E_BASE_URL=http://nginx:80
      - E2E_BACKEND_URL=http://backend:8000
      - E2E_POSTGRES_URL=postgresql://codify:codify_password@postgres:5432/codify
```

### 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `E2E_BASE_URL` | `http://nginx:80` | 前端 Nginx 地址 |
| `E2E_BACKEND_URL` | `http://backend:8000` | 后端 API 地址 |
| `E2E_GITLAB_URL` | `http://gitlab:8080` | GitLab 地址 |
| `E2E_POSTGRES_URL` | `postgresql://...` | PostgreSQL 数据库地址 |

### 重新构建镜像

修改代码后必须重新构建 Docker 镜像：

```bash
# 重新构建 backend 镜像（修改 backend 代码后需要）
docker build -f deploy/Dockerfile.backend -t codify-backend:latest .

# 重新构建 worker 镜像（修改 worker 脚本后需要）
docker build -f deploy/Dockerfile.worker-java21-maven -t codify-worker/java21-maven:2026.07 .

# 或一次性构建所有镜像并重启
cd deploy && docker-compose up -d --build
```

> **注意**：worker 容器执行的 entrypoint 来自 Task Runtime Bundle（backend 在任务创建时从镜像内
> `/opt/codify/runtime-source` 生成）。改动 `deploy/worker-entrypoint/**` 或 `ci-claude.sh` 后必须重建
> backend 镜像并 recreate scheduler，retry 任务复用旧 bundle digest，要验证新改动必须**新建**任务。
> 详见 [dev-env-api-regression.md](dev-env-api-regression.md) §8。

---

## 运行测试

### 本地运行（不通过 Docker）

如果需要在本地直接运行测试（非 Docker 环境）：

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

### 使用可见浏览器调试

```bash
# 运行测试时显示浏览器窗口
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v --headed
```

### 查看测试报告

```bash
# 生成 HTML 报告
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/ -v --html=report.html --self-contained-html

# 查看报告（在宿主机上）
docker cp <container_id>:/app/report.html ./
```

---

## 并行 / 串行架构

测试套件用 **pytest-xdist 并行执行**（`-n auto --dist=loadfile`）。状态无关测试并行跑，状态相关测试串行跑。

```
pytest -n auto --dist=loadfile
      │
      ├─ gw0 ── test_dashboard.py ──── test_admin_gw0 用户
      ├─ gw1 ── test_navigation.py ─── test_admin_gw1 用户
      ├─ gw2 ── test_create_task.py ── test_admin_gw2 用户
      └─ gw3 ── test_task_view.py ──── test_admin_gw3 用户
```

**串行 / 并行关键机制：**

| 组件 | 串行模式 | 并行（xdist）模式 |
|------|---------|----------------|
| 管理员用户 | `test_admin`（每次测试重新注册） | `test_admin_gw0/gw1/…`（session 级别，各 worker 独立） |
| 用户创建方式 | `POST /api/auth/local/register` | 直接 INSERT DB（绕过 API 竞态） |
| 密码 Hash | 600,000 次 PBKDF2 | 1 次 PBKDF2（快速；backend 从 hash 字符串读取迭代次数） |
| `reset_database` | 清空全部 users + sessions + 重置 bootstrap | 仅删除**本 worker** 的 sessions（不碰其他 worker 的用户） |
| `_api_login` | register→fallback login | 直接 `/login`（system 已初始化） |
| `PYTEST_XDIST_WORKER` | 未设置 | 设置为 `gw0`, `gw1`, … |

**串行组自动跳过：** 修改共享 DB 状态的测试（`test_bootstrap.py` / `test_prompt_template.py` / `test_access_management.py`）顶部带 `pytestmark = skipif(PYTEST_XDIST_WORKER)`，在 xdist worker 中自动跳过，须用 `make test-e2e-serial` 单独运行。

如何判断一个测试该并行还是串行，见「[编写新测试用例的规则](#编写新测试用例的规则)」中的分组规则。

---

## 测试结构

### 测试文件模板

```python
"""
测试文件描述

Tests for the [功能模块] page functionality including:
- 功能点1
- 功能点2
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.[marker_name]
class Test[ComponentName]:
    """Tests for the [组件名称] functionality."""

    def test_feature_one(self, logged_in_page: Page, reset_database):
        """Test description."""
        logged_in_page.goto("/page-path")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".selector")).to_be_visible()

    def test_feature_two(self, logged_in_page: Page, reset_database):
        """Test another feature."""
        # ...
```

### 测试标记 (Markers)

| 标记 | 用途 |
|------|------|
| `@pytest.mark.bootstrap` | Bootstrap 页面测试 |
| `@pytest.mark.dashboard` | 仪表盘测试 |
| `@pytest.mark.create_task` | 创建任务页面测试 |
| `@pytest.mark.task_view` | 任务详情页测试 |
| `@pytest.mark.task_details` | 任务详情组件测试 |
| `@pytest.mark.manual_task` | 手动任务测试 |
| `@pytest.mark.prompt_template` | Prompt 模板测试 |
| `@pytest.mark.access` | 访问管理测试 |
| `@pytest.mark.navigation` | 导航测试 |

> **并行/串行分组规则**（重要）：无状态测试放入并行文件；修改共享 DB 状态
> （bootstrap / prompt_template / access_management）的测试必须带 `pytestmark = skipif(PYTEST_XDIST_WORKER)`
> 走串行。详见 [TESTING.md](TESTING.md) §5。

---

## 编写测试

### 基础测试示例

```python
@pytest.mark.dashboard
class TestDashboardPage:
    """Tests for the dashboard page functionality."""

    def test_dashboard_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the dashboard page loads without errors."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("networkidle")
        expect(logged_in_page.locator(".dashboard__title")).to_be_visible()

    def test_dashboard_has_filters(self, logged_in_page: Page, reset_database):
        """Test that dashboard has filter dropdowns."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("networkidle")
        filter_selects = logged_in_page.locator(".dashboard__filters .n-select")
        expect(filter_selects.first).to_be_visible()
```

### 使用 Page Object 模式

```python
@pytest.mark.create_task
class TestCreateTaskFormFields:
    """Tests for create task form field presence."""

    def test_project_selector_exists(self, logged_in_page: Page, reset_database):
        """Test that project selector is present in the form."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        project_select = logged_in_page.locator(".create-task-form").locator(".n-select").first
        expect(project_select).to_be_visible()

    def test_prompt_editor_exists(self, logged_in_page: Page, reset_database):
        """Test that the prompt editor (VariableEditor) is present."""
        logged_in_page.goto("/create-task")
        logged_in_page.wait_for_load_state("networkidle")
        variable_editor = logged_in_page.locator(".variable-editor")
        expect(variable_editor).to_be_visible()
```

### 常见选择器模式

```python
# 按角色选择
page.get_by_role("button", name="Submit")
page.get_by_role("tab", name="Settings")

# 按文本选择
page.get_by_text("Create Task")
page.locator(".nav-menu").get_by_text("Dashboard")

# 按占位符选择
page.get_by_placeholder("Enter your name")

# CSS 选择器
page.locator(".dashboard__filters .n-select")
page.locator("#prompt-templates-settings")

# 组合选择器
page.locator(".n-card input").first
page.locator(".variable-editor .cm-content")
```

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

---

## Fixtures 详解

### logged_in_page

这是最常用的 fixture，用于需要登录认证的测试。

```python
def test_requires_auth(self, logged_in_page: Page, reset_database):
    """Test that requires authentication."""
    logged_in_page.goto("/dashboard")
    # ...
```

**工作流程：**
1. 调用 `reset_database` 确保数据库是干净状态
2. 打开浏览器页面
3. 如果系统未初始化，通过 bootstrap 创建管理员
4. 如果系统已初始化，通过登录页面登录
5. 返回已认证的页面对象

> 在 xdist 并行模式下 `logged_in_page` 自动切换为「直插用户 + 直接 /login」以规避注册竞态，
> 与串行模式的实现不同，无需测试作者关心。

### reset_database

每个测试前后重置数据库状态：

```python
def test_something(self, logged_in_page: Page, reset_database):
    # 测试前：删除所有用户和会话，重置系统为未初始化状态
    # 测试执行
    # 测试后：再次重置数据库
```

**重置操作：**
- 删除 `user_sessions` 表
- 删除 `users` 表
- 重置 `system_bootstrap` 为未初始化状态

> xdist 并行模式下 `reset_database` 只删除**本 worker** 的 sessions，不碰其他 worker 的用户。

### page

基础 fixture，提供未认证的浏览器页面：

```python
def test_public_page(self, page: Page, reset_database):
    """Test public page without authentication."""
    page.goto("/login")
    # ...
```

### setup_database

Session 级别的数据库连接，通常不需要直接使用。

---

## 常见问题

### Playwright 测试类

**1. 测试超时**

原因：页面加载慢或元素未及时出现。

```python
# 方案1：增加超时
page.wait_for_load_state("networkidle", timeout=30000)

# 方案2：等待元素
page.wait_for_selector(".element", timeout=10000)

# 方案3：固定等待
page.wait_for_timeout(2000)
```

**2. 严格模式冲突**

原因：选择器匹配到多个元素。错误：`Error: strict mode violation: locator(".n-card") resolved to 6 elements`。

```python
expect(page.locator(".n-card").first).to_be_visible()
expect(page.locator(".n-modal")).to_be_visible()
expect(page.get_by_role("dialog").get_by_text("Name")).to_be_visible()
```

**3. URL 匹配失败**

```python
assert "/dashboard" in page.url
expect(page).to_have_url("**/dashboard", timeout=5000)
```

**4. 表名不存在**

错误：`relation "sessions" does not exist`。数据库表名是 `user_sessions` 而不是 `sessions`。

```bash
docker exec codify-e2e-postgres psql -U codify -d codify -c "\dt"
```

**5. 滚动元素不可见**

```python
element = page.locator(".n-tabs-tab").nth(6)
element.scroll_into_view_if_needed()
element.click()
```

**6. 日期时间时区问题**

错误：`can't subtract offset-naive and offset-aware datetimes`。Backend 已修复，使用 `.replace(tzinfo=None)`。

### 基础设施 / 集成调试类

**7. Token 泄露问题**

症状：错误日志中暴露了 GitLab Token (`glpat-xxx`) 或 API Key (`sk-xxx`)。

原因：日志直接输出敏感信息；数据库错误信息未脱敏。

解决：worker 日志在存储前统一经 `harness/adapters/sanitize.py` 的 `sanitize_sensitive_data()` 脱敏
（移除 `glpat-*`、`sk-ant-*` 及 null 字节）。在存储 error_message / task_logs / 发送到外部系统前调用。

**8. 数据库编码错误**

症状：`CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8": 0x00`。

原因：日志中包含 null 字节 (`\x00`)。脱敏函数中已处理 `text.replace('\x00', '')`。

**9. 任务状态卡住**

症状：任务状态一直是 `running`，但容器已退出。

```bash
# 检查任务状态
docker exec codify-e2e-postgres psql -U codify -d codify -c "SELECT id, status FROM tasks ORDER BY id DESC LIMIT 5;"

# 检查容器状态与日志
docker ps -a | grep codify
docker logs <container_id>
```

> 定位 CLI 层问题的第一现场是 archive 里的 `harness-events/<harness>.jsonl`，详见
> [multi-harness-debugging.md](multi-harness-debugging.md)。

**10. 日志截断问题**

症状：错误信息不完整，只看到部分日志。

解决：增加日志存储长度（`error_message` 与 `TaskLog.message` 的截断上限）。

**11. Shell Heredoc 语法错误**

症状：Python 脚本报 `SyntaxError: unmatched ')'`。

原因：在 `<<'PYTHON_SCRIPT'` heredoc 内错误放置了 bash 代码。bash 代码应放在 heredoc 结束后。

---

## 调试技巧

### 使用可见浏览器

```bash
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v --headed
```

### 添加截图

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Debug test with screenshot."""
    logged_in_page.goto("/dashboard")
    logged_in_page.wait_for_load_state("networkidle")
    logged_in_page.screenshot(path="/tmp/dashboard.png")
    print("Screenshot saved")
```

### 打印页面内容

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Debug test with page content."""
    logged_in_page.goto("/dashboard")
    logged_in_page.wait_for_load_state("networkidle")
    body_text = logged_in_page.locator("body").inner_text()
    print(f"Page content: {body_text[:500]}")
```

### 交互式调试

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Interactive debug session."""
    logged_in_page.goto("/dashboard")
    logged_in_page.wait_for_load_state("networkidle")
    import pdb; pdb.set_trace()  # 需要 --headed 模式
```

### 检查元素状态

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Debug element visibility."""
    logged_in_page.goto("/config")
    logged_in_page.wait_for_load_state("networkidle")
    tabs = logged_in_page.locator(".n-tabs-tab")
    print(f"Total tabs: {tabs.count()}")
    for i in range(tabs.count()):
        tab = tabs.nth(i)
        print(f"Tab {i}: {tab.inner_text()}, visible: {tab.is_visible()}")
```

---

## 调试命令速查

```bash
# 1. 启动 E2E 环境
cd deploy && docker-compose -f docker-compose.e2e.yml up -d

# 2. 运行所有测试
docker-compose -f docker-compose.e2e.yml run --rm e2e

# 3. 运行单个测试文件
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v

# 4. 运行带标记的测试
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest -m dashboard -v

# 5. 带浏览器窗口运行
docker-compose -f docker-compose.e2e.yml run --rm e2e pytest tests/e2e/tests/test_dashboard.py -v --headed

# 6. 查看容器日志
docker logs codify-e2e-backend --tail 100
docker logs codify-e2e-backend --tail 100 2>&1 | grep -i "task\|error"

# 7. 查看数据库任务状态
docker exec codify-e2e-postgres psql -U codify -d codify -c "SELECT id, status, error_message FROM tasks ORDER BY id DESC LIMIT 3;"

# 8. 查看任务日志（完整输出）
docker exec codify-e2e-postgres psql -U codify -d codify -c "SELECT message FROM task_logs WHERE task_id = <id>;"

# 9. 检查数据库表
docker exec codify-e2e-postgres psql -U codify -d codify -c "\dt"

# 10. 查看当前运行的容器
docker ps -a | grep codify

# 11. 清理环境
docker-compose -f docker-compose.e2e.yml down -v

# 12. 重新构建镜像（代码修改后必须）
docker build --no-cache -f deploy/Dockerfile.e2e -t codify-e2e:latest .
```

---

## GitLab 集成验证

真实 GitLab E2E 测试（`tests/gitlab_e2e/`）验证完整 worker 链路（真实 GitLab + 真实 Harness CLI）。
此类测试**只应跑在隔离测试环境**，可能创建任务、分支、MR、Issue 评论。

### 测试检查清单

运行集成测试后，验证以下项目：

- [ ] Issue 评论显示开始通知
- [ ] Issue 评论显示完成通知（带 MR 链接）
- [ ] MR 有实际提交（SHA 不为 null）
- [ ] MR 无冲突
- [ ] 任务状态为 completed（不是 running/failed）
- [ ] 错误日志中无 Token 泄露
- [ ] archive 的 `harness-events/<harness>.jsonl` 可回放（canonical 事件一致）

### 常用 GitLab API 端点（开发环境）

```
GitLab 地址: http://192.168.50.129:8080

# Issue 相关
GET  /api/v4/projects/1/issues              # 列出 Issue
GET  /api/v4/projects/1/issues/{iid}        # 获取 Issue
POST /api/v4/projects/1/issues               # 创建 Issue
GET  /api/v4/projects/1/issues/{iid}/notes  # 获取 Issue 评论

# MR 相关
GET  /api/v4/projects/1/merge_requests              # 列出 MR
GET  /api/v4/projects/1/merge_requests/{iid}        # 获取 MR
GET  /api/v4/projects/1/repository/commits?ref_name=branch  # 查看提交

# 项目相关
GET  /api/v4/projects/1                     # 获取项目信息
GET  /api/v4/projects/1/repository/branches # 列出分支
```

---

## 相关文件

- `backend/tests/e2e/conftest.py` - Fixtures 和配置
- `backend/tests/e2e/requirements-e2e.txt` - 测试依赖
- `backend/tests/gitlab_e2e/` - 真实 GitLab 集成测试
- `deploy/docker-compose.e2e.yml` - 测试环境配置
- `deploy/Dockerfile.e2e` - 测试容器构建
