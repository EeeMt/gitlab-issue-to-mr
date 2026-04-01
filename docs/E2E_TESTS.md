# E2E 测试指南

本文档介绍 GIMR 项目的 Playwright E2E 浏览器测试的开发、运行和调试方法。

## 目录

- [快速开始](#快速开始)
- [环境配置](#环境配置)
- [运行测试](#运行测试)
- [测试结构](#测试结构)
- [编写测试](#编写测试)
- [Fixtures 详解](#fixtures-详解)
- [常见问题](#常见问题)
- [调试技巧](#调试技巧)

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
    image: gimr-backend:latest
    environment:
      - DATABASE_URL=postgresql+asyncpg://gimr:gimr_password@postgres:5432/gimr
      - AUTO_MIGRATE=true

  nginx:
    image: gimr-nginx:latest

  e2e:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.e2e
    command: pytest tests/e2e/tests/ -v  # 默认运行所有测试
    environment:
      - E2E_BASE_URL=http://nginx:80
      - E2E_BACKEND_URL=http://backend:8000
      - E2E_POSTGRES_URL=postgresql://gimr:gimr_password@postgres:5432/gimr
```

### 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `E2E_BASE_URL` | `http://nginx:80` | 前端 Nginx 地址 |
| `E2E_BACKEND_URL` | `http://backend:8000` | 后端 API 地址 |
| `E2E_GITLAB_URL` | `http://gitlab:8080` | GitLab 地址 |
| `E2E_POSTGRES_URL` | `postgresql://...` | PostgreSQL 数据库地址 |

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
# （需要有 PostgreSQL 和 Redis 运行）

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

### 处理动态加载元素

```python
def test_element_with_scroll(self, logged_in_page: Page, reset_database):
    """Test element that requires scrolling."""
    logged_in_page.goto("/config")
    logged_in_page.wait_for_load_state("networkidle")
    logged_in_page.wait_for_timeout(1000)  # 等待页面稳定

    # 滚动到元素位置
    prompt_tab = logged_in_page.locator(".n-tabs-tab").nth(6)
    prompt_tab.scroll_into_view_if_needed()
    prompt_tab.click()
    logged_in_page.wait_for_timeout(1000)
```

### 处理多个匹配元素

```python
def test_multiple_elements(self, logged_in_page: Page, reset_database):
    """Test when selector matches multiple elements."""
    # 使用 .first 选择第一个
    refresh_button = logged_in_page.get_by_role("button", name="Refresh").first

    # 或使用更具体的选择器
    logs_refresh = logged_in_page.locator(".task-card").get_by_role("button", name="Refresh")
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

### 1. 测试超时

**原因：** 页面加载慢或元素未及时出现

**解决方案：** 增加等待时间
```python
# 方案1：增加超时
page.wait_for_load_state("networkidle", timeout=30000)

# 方案2：等待元素
page.wait_for_selector(".element", timeout=10000)

# 方案3：固定等待
page.wait_for_timeout(2000)
```

### 2. 严格模式冲突

**原因：** 选择器匹配到多个元素

**错误信息：**
```
Error: strict mode violation: locator(".n-card") resolved to 6 elements
```

**解决方案：**
```python
# 使用 .first
expect(page.locator(".n-card").first).to_be_visible()

# 或更具体的选择器
expect(page.locator(".n-modal")).to_be_visible()
expect(page.get_by_role("dialog").get_by_text("Name")).to_be_visible()
```

### 3. URL 匹配失败

**原因：** `to_have_url` 使用精确匹配或正则表达式匹配

**解决方案：**
```python
# 使用简单的字符串包含
assert "/dashboard" in page.url

# 或使用更宽松的正则
expect(page).to_have_url("**/dashboard", timeout=5000)
```

### 4. 表名不存在

**错误：** `relation "sessions" does not exist`

**原因：** 数据库表名是 `user_sessions` 而不是 `sessions`

**检查表名：**
```bash
docker exec gimr-e2e-postgres psql -U gimr -d gimr -c "\dt"
```

### 5. 滚动元素不可见

**原因：** 元素在视口外或被遮挡

**解决方案：**
```python
element = page.locator(".n-tabs-tab").nth(6)
element.scroll_into_view_if_needed()
element.click()
```

### 6. 日期时间时区问题

**错误：** `can't subtract offset-naive and offset-aware datetimes`

**原因：** Backend 代码使用 `datetime.now(UTC)` 但数据库存储为 naive datetime

**解决：** Backend 已修复，使用 `.replace(tzinfo=None)`

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

    # 截图保存
    logged_in_page.screenshot(path="/tmp/dashboard.png")
    print("Screenshot saved")
```

### 打印页面内容

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Debug test with page content."""
    logged_in_page.goto("/dashboard")
    logged_in_page.wait_for_load_state("networkidle")

    # 打印 body 文本
    body_text = logged_in_page.locator("body").inner_text()
    print(f"Page content: {body_text[:500]}")

    # 列出所有按钮
    buttons = logged_in_page.get_by_role("button").all()
    for btn in buttons:
        print(f"Button: {btn.inner_text()}")
```

### 交互式调试

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Interactive debug session."""
    logged_in_page.goto("/dashboard")
    logged_in_page.wait_for_load_state("networkidle")

    # 在此处设置断点（需要 --headed 模式）
    import pdb; pdb.set_trace()

    # 或者只是打印调试信息
    import logging
    logging.basicConfig(level=logging.DEBUG)
```

### 检查元素状态

```python
def test_debug(self, logged_in_page: Page, reset_database):
    """Debug element visibility."""
    logged_in_page.goto("/config")
    logged_in_page.wait_for_load_state("networkidle")

    # 检查标签页
    tabs = logged_in_page.locator(".n-tabs-tab")
    print(f"Total tabs: {tabs.count()}")

    for i in range(tabs.count()):
        tab = tabs.nth(i)
        print(f"Tab {i}: {tab.inner_text()}, visible: {tab.is_visible()}")

    # 检查 bounding box
    tab_6 = logged_in_page.locator(".n-tabs-tab").nth(6)
    bb = tab_6.bounding_box()
    print(f"Tab 6 bounding box: {bb}")
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
docker logs gimr-e2e-backend --tail 100
docker logs gimr-e2e-postgres --tail 100

# 7. 进入测试容器
docker run --rm -it --network=deploy_gimr-e2e-network gimr-e2e:latest /bin/bash

# 8. 检查数据库表
docker exec gimr-e2e-postgres psql -U gimr -d gimr -c "\dt"

# 9. 清理环境
docker-compose -f docker-compose.e2e.yml down -v

# 10. 重新构建镜像（代码修改后必须）
docker build --no-cache -f deploy/Dockerfile.e2e -t gimr-e2e:latest .
```

---

## 相关文件

- `backend/tests/e2e/conftest.py` - Fixtures 和配置
- `backend/tests/e2e/requirements-e2e.txt` - 测试依赖
- `deploy/docker-compose.e2e.yml` - 测试环境配置
- `deploy/Dockerfile.e2e` - 测试容器构建
- `docs/e2e-debugging.md` - 集成测试调试指南（GitLab E2E）
