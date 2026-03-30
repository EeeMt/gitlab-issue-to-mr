# GIMR 项目可维护性/稳定性提升策划文档

## 背景

本次重构目标是提升 GIMR (GitLab Issue to MR Bot) 项目的**可维护性**和**稳定性**，包括：
- 模块划分优化
- 代码结构优化
- 测试用例的完善和优化
- 错误处理和类型安全

---

## 重构工作流程 SOP

每次重构任务需遵循以下流程：

### 步骤 1: 创建任务分支

```bash
# 基于 main 创建重构分支
git checkout main
git pull origin main
git checkout -b refactor/<task-name>
```

### 步骤 2: 评估测试需求

**在实现代码改动前，评估是否需要新增或修改测试用例：**

- [ ] 如果修改涉及 Bug 修复：确认是否有对应测试覆盖该 Bug
- [ ] 如果修改涉及新功能：确认是否有对应测试覆盖该功能
- [ ] 如果修改涉及重构：确认现有测试是否能验证功能不变
- [ ] 如果缺少测试覆盖：先编写测试，再修改代码（测试先行原则）

**评估标准：**
- Bug 修复类改动：必须验证有测试覆盖
- 重构类改动：必须确保现有测试通过
- 新功能类改动：必须新增测试

### 步骤 3: 实现改动

按照 Phase 计划执行代码改动：
- 遵循 Phase 顺序执行
- 每次只做一件事 (small PR 原则)
- 确保改动最小化

### 步骤 4: 运行测试验证

```bash
# 1. 运行受影响的单元测试
cd backend && pytest tests/unit/ -v --tb=short -k "<relevant_test_name>"

# 2. 运行相关模块的完整测试
cd backend && pytest tests/unit/ -v --tb=short

# 3. 运行 Mock E2E (如果改动影响集成)
cd backend && pytest tests/mock_e2e/ -v

# 4. 如果有前端改动，运行 E2E
cd backend && pytest tests/e2e/ -v
```

**通过标准:** 所有测试必须通过，无新的 warning

### 步骤 5: Code Review + 变更分析

**A. 变更分析:**

```bash
# 查看改动统计
git diff --stat

# 查看具体改动
git diff
```

分析要点：
- 改动的文件数和行数
- 是否有意外的大范围改动
- 是否引入了新的依赖
- 是否有潜在的性能影响

**B. Review 自查清单:**
- [ ] 代码符合项目的命名规范
- [ ] 公共 API 有适当的文档
- [ ] 复杂逻辑有注释说明
- [ ] 敏感数据处理正确
- [ ] 错误处理完整
- [ ] 类型注解完整 (新增代码)
- [ ] 测试覆盖充分

### 步骤 6: 更新进度文档

在 `refactoring/PROGRESS.md` 中记录：

```markdown
## YYYY-MM-DD 任务名称

### 完成
- [x] 具体完成的改动

### 测试验证
- 单元测试: ✅ 通过
- Mock E2E: ✅ 通过

### 变更分析
- 文件改动: X 个
- 新增行数: +XXX
- 删除行数: -XXX

### 遗留问题 / 后续待办
- [ ] 待解决的问题
- [ ] 后续可以优化的点
```

### 步骤 7: 提交代码

```bash
# 1. 添加改动的文件
git add <changed_files>

# 2. 提交 (遵循 commit 规范)
git commit -m "refactor(<module>): <具体描述>

- <改动点1>
- <改动点2>

Refs: #<相关issue>"
```

**Commit 类型规范:**
- `refactor:` - 代码重构
- `fix:` - Bug 修复
- `test:` - 测试相关
- `docs:` - 文档更新
- `perf:` - 性能优化

### 步骤 8: 推送和创建 MR

```bash
# 推送分支
git push -u origin refactor/<task-name>

# 创建 MR (通过 GitLab UI 或 gh)
```

---

## 现状分析总结

### 代码组织问题

| 问题 | 文件 | 严重度 |
|------|------|--------|
| 文件过大 (1441行) | `api/config.py` | Critical |
| 文件过大 (860行) | `api/tasks.py` | High |
| 文件过大 (824行) | `core/worker.py` | High |
| 代码位置错误 | `webhook.py` 中的 prompt building | Medium |
| 重复 `get_settings()` | scheduler.py, worker.py | Low |

### 代码质量问题

| 问题 | 位置 | 严重度 |
|------|------|--------|
| Bare `except:` 导致未定义变量 `e` | `docker_client.py:135` | Critical |
| 异步函数中使用同步 `requests` | `gitlab_client.py:219`, `worker.py:791` | High |
| `execute_task()` 354行，违反单一职责 | `worker.py:276-630` | Medium |
| 缺少返回类型注解 | `get_settings()` 多处 | Low |
| 深度嵌套代码 | `worker.py:330-365` | Medium |

### 测试覆盖问题

| 问题 | 状态 | 优先级 |
|------|------|--------|
| 无 DockerClientWrapper 单元测试 | 0 tests | High |
| 无共享 `conftest.py` | missing | High |
| API endpoints 缺少测试 | containers, stats | High |
| 使用 print 而非 pytest 断言 | `test_webhook.py` | Medium |
| 过度 mock 而非真实行为测试 | `test_priority.py` | Medium |
| E2E 测试覆盖不足 | 关键流程缺失 | High |

---

## Phase 1: 代码结构重构 (模块划分优化)

### 1.1 拆分 `api/config.py` (Critical - 1441行)

**目标:** 将巨大的 config.py 拆分为职责明确的模块

**拆分会出现的文件:**
- `api/config.py` - Runtime config API (~300行)
- `api/mattermost.py` - Mattermost profile CRUD (~400行)
- `api/oidc.py` - OIDC 配置 (~300行)
- `api/project_webhooks.py` - 项目 webhook 配置 (~200行)

**操作:**
```bash
# 1. 创建新文件
# 2. 移动相关代码
# 3. 更新 imports
# 4. 更新路由注册
```

### 1.2 拆分 `core/worker.py` (High - 824行)

**目标:** 将 `execute_task()` 拆分为职责明确的辅助方法

**提取的方法:**
- `_create_mr_if_needed()` - MR 创建逻辑
- `_build_container_env()` - 环境变量构建
- `_process_task_result()` - 结果处理
- `_send_notifications()` - 通知发送
- `_update_mr_description()` - MR 描述更新

**注意:** 保持 public API 不变，内部重构

### 1.3 移动错误放置的代码 (Medium)

**`api/webhook.py` -> `core/parser.py`:**
- `build_enhanced_prompt()` (lines 63-80)
- `build_prompt_with_issue_context()` (lines 82-107)

**操作:** 移动到 parser.py，更新 imports

### 1.4 消除重复代码 (Medium)

**重复的 `get_settings()` wrapper:**
- `scheduler.py:30`
- `worker.py:87`

**操作:** 删除本地 wrapper，直接使用 `from app.config import get_effective_settings as get_settings`

**重复的 `_build_project_lookup()`:**
- `api/tasks.py:50-59`
- `api/stats.py:88-112`

**操作:** 提取到 `core/projects.py` 作为共享函数

### 1.5 拆分 `api/tasks.py` (High - 860行)

**目标:** 提取共享代码，减少文件体积

**提取内容:**
- `_build_project_lookup()` -> `core/projects.py`
- 验证逻辑可以内联简化

**注意:** 该文件路由较多，不做大幅拆分，只提取共享逻辑

---

## Phase 2: 代码质量提升

### 2.1 修复 Critical Bug: Bare `except:` (Critical)

**文件:** `backend/app/core/docker_client.py:133-136`

**当前代码:**
```python
try:
    logs = container.logs(stdout=True, stderr=True).decode("utf-8")
except:  # BUG: bare except
    logs = f"Failed to get logs: {e}"  # BUG: e is undefined
```

**修复:**
```python
try:
    logs = container.logs(stdout=True, stderr=True).decode("utf-8")
except Exception as e:
    logs = f"Failed to get logs: {e}"
```

### 2.2 修复异步中使用同步 requests (High)

**文件:** `gitlab_client.py:217-224`
**文件:** `worker.py:789-795`

**修复方案:** 使用 `httpx.AsyncClient` 替代 `requests`

```python
# Before
import requests
response = requests.get(url, headers={...}, timeout=30)

# After
import httpx
async with httpx.AsyncClient() as client:
    response = await client.get(url, headers={...}, timeout=30)
```

### 2.3 添加类型注解 (Medium)

**目标文件:**
- `scheduler.py` - `get_settings()` 返回类型
- `worker.py` - `get_settings()` 返回类型
- `docker_client.py` - Container 参数类型

**示例:**
```python
def get_settings() -> Settings:
    """Get effective settings (with runtime overrides)."""
    return get_effective_settings()
```

### 2.4 简化深度嵌套代码 (Medium)

**文件:** `worker.py:330-365` (MR 创建逻辑)

**重构:** 使用早期返回和提取方法减少嵌套

---

## Phase 3: 测试基础设施完善

### 3.1 创建共享 `conftest.py` (High)

**文件:** `backend/tests/unit/conftest.py` (新建)

**内容:**
```python
import os
import pytest
from unittest.mock import MagicMock, AsyncMock

# 共享 fixtures:
@pytest.fixture
def mock_settings():
    """Mock settings with sensible defaults"""
    ...

@pytest.fixture
def mock_db_session():
    """Standard mock async database session"""
    ...

@pytest.fixture
def clean_singletons():
    """Reset all singletons before/after test"""
    from app.core.gitlab_client import reset_gitlab_client
    from app.runtime_config import reset_runtime_config
    reset_gitlab_client()
    reset_runtime_config()
    yield
    reset_gitlab_client()
    reset_runtime_config()
```

### 3.2 添加 DockerClientWrapper 单元测试 (High)

**文件:** `backend/tests/unit/test_docker_client.py` (新建)

**测试覆盖:**
- `pull_image()` - force/non-force, local/remote
- `create_container()` - volumes, environment, networking
- `wait_for_container()` - timeout, success, failure cases
- `remove_container()` - force/graceful
- `get_container_logs()`

### 3.3 修复 Print-Based 测试 (Medium)

**文件:** `backend/tests/unit/test_webhook.py`

**将 print 断言转换为 pytest:**
```python
# Before
if errors:
    print(f"❌ FAIL: {tc['name']}")
    failed += 1

# After
assert len(errors) == 0, f"{tc['name']}: {errors}"
```

### 3.4 添加 API Endpoint 测试 (High)

**新建测试文件:**
- `backend/tests/unit/test_containers_api.py` - 测试 `api/containers.py`
- `backend/tests/unit/test_stats_api.py` - 测试 `api/stats.py`

**使用 FastAPI TestClient:**
```python
from fastapi.testclient import TestClient

def test_list_containers_empty():
    """Test containers endpoint returns empty list"""
    ...
```

### 3.5 改进 E2E 测试覆盖 (High)

**当前缺失的关键流程:**
- Dashboard task queue viewing
- Task detail view with logs
- Manual task creation via UI
- Task cancel/retry actions

**建议:** 在 `tests/e2e/tests/` 添加:
- `test_task_queue.py`
- `test_task_details.py`
- `test_manual_task.py`

---

## Phase 4: 稳定性增强

### 4.1 添加敏感数据清理测试 (Medium)

**文件:** `backend/tests/unit/test_scrubbing.py` (新建)

**测试函数:**
- `scrub_sensitive_data()` - GitLab tokens, API keys
- `sanitize_sensitive_data()` - ANSI escape codes, null bytes

### 4.2 添加 Scheduler 核心逻辑测试 (Medium)

**扩展:** `backend/tests/unit/test_scheduler_split.py`

**测试:**
- Priority queue ordering
- Issue mutex behavior
- Concurrency limiting

### 4.3 添加 GitLab Client 重试测试 (Medium)

**扩展:** `backend/tests/unit/test_gitlab_client_access.py`

**测试:**
- API 错误处理
- 超时行为
- Rate limit 响应

---

## 关键文件清单

### 需要拆分/重构的文件
| 文件 | 当前行数 | 目标 |
|------|----------|------|
| `backend/app/api/config.py` | 1441 | 拆分为 4 个模块 |
| `backend/app/api/tasks.py` | 860 | 提取共享代码 |
| `backend/app/core/worker.py` | 824 | 提取辅助方法 |

### 需要新建的测试文件
| 文件 | 优先级 |
|------|--------|
| `backend/tests/unit/conftest.py` | High |
| `backend/tests/unit/test_docker_client.py` | High |
| `backend/tests/unit/test_containers_api.py` | High |
| `backend/tests/unit/test_stats_api.py` | High |
| `backend/tests/unit/test_scrubbing.py` | Medium |

### 需要修复 Bug 的文件
| 文件 | 问题 |
|------|------|
| `backend/app/core/docker_client.py:135` | Bare except 导致 NameError |
| `backend/app/core/gitlab_client.py:219` | 同步 requests in async |
| `backend/app/core/worker.py:791` | 同步 requests in async |

---

## 实施顺序

**优先级说明:**
- P0: Critical bug，必须立即修复
- P1: 高优先级，影响稳定性
- P2: 中优先级，改善可维护性

```
P0 (立即执行):
  2.1 修复 bare except bug          # Critical bug - NameError

P1 (优先执行):
  3.1 创建共享 conftest.py           # 其他测试任务依赖
  2.2 修复 async/requests 问题       # 潜在死锁风险
  1.3 移动错误放置的代码             # 低风险，小改动
  1.4 消除重复代码                   # 低风险，小改动

Phase 1 (模块划分 - 4-6周):
  1.1 拆分 api/config.py
    1.1.1 先拆分 oidc.py (最独立)
    1.1.2 再拆分 project_webhooks.py
    1.1.3 最后拆分 mattermost.py
    1.1.4 保留 config.py 仅含 Runtime config
  1.2 拆分 core/worker.py
  1.5 拆分 api/tasks.py              # 新增: 860行也需要处理

Phase 2 (代码质量 - 1-2周):
  2.3 添加类型注解
  2.4 简化深度嵌套

Phase 3 (测试完善 - 2-3周):
  3.2 添加 DockerClientWrapper 测试   # 依赖 3.1
  3.3 修复 print-based 测试
  3.4 添加 API endpoint 测试
  3.5 改进 E2E 覆盖

Phase 4 (稳定性 - 1-2周):
  4.1 敏感数据清理测试
  4.2 Scheduler 核心逻辑测试
  4.3 GitLab Client 重试测试
```

**任务依赖关系:**
```
3.1 (conftest) ─┬─> 3.2 (DockerClient 测试)
                 └─> 3.4 (API 测试)

1.1.1 (拆 oidc) ─> 1.1.2 ─> 1.1.3 ─> 1.1.4 (拆 config.py)

2.2 (async/requests)  ─> 2.3 (类型注解) ─> 2.4 (简化嵌套)
```

---

## 验证方式

```bash
# 1. 运行单元测试
cd backend && pytest tests/unit/ -v --tb=short

# 2. 运行 Mock E2E
cd backend && pytest tests/mock_e2e/ -v

# 3. 检查代码行数 (验证拆分)
wc -l backend/app/api/config.py  # 应该 < 400

# 4. 类型检查
cd backend && mypy app/ --ignore-missing-imports

# 5. E2E 测试
cd backend && pytest tests/e2e/ -v
```

---

## 风险评估

| 变更 | 风险 | 缓解措施 |
|------|------|----------|
| 拆分 config.py | 高 - 涉及路由 | 先拆分新文件，逐步迁移 |
| 拆分 worker.py | 中 - 内部重构 | 保持 public API 不变 |
| 修改测试框架 | 低 | 增量修改，保留旧测试 |

---

## 成果统计

| 指标 | 目标 | 当前 |
|------|------|------|
| 代码行数 (config.py) | < 400 | 1441 |
| 代码行数 (worker.py) | < 500 | 824 |
| 代码行数 (tasks.py) | < 500 | 860 |
| 测试覆盖率 | > 80% | ~45% (需确认) |
| 类型注解完整度 | 100% | - |
| Critical bugs | 0 | 1 (bare except) |
