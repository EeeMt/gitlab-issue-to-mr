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

### Frontend 代码组织问题

| 问题 | 文件 | 严重度 |
|------|------|--------|
| 无测试框架 | `package.json` | Critical |
| 文件过大 (800行) | `views/CreateTask.vue` | High |
| 文件过大 (900行) | `views/TaskView.vue` | High |
| 文件过大 (490行) | `views/Dashboard.vue` | Medium |
| 复杂编辑器逻辑 | `components/VariableEditor.vue` | Medium |

### Frontend 代码质量问题

| 问题 | 位置 | 严重度 |
|------|------|--------|
| 缺少测试基础设施 | 整个 frontend | Critical |
| 复杂表单状态管理 | `CreateTask.vue` - schedule/buildScheduleRequest | High |
| 实时日志流处理 | `TaskView.vue` - EventSource/logStream | High |
| 自动刷新逻辑 | `Dashboard.vue` - pollTimer | Medium |
| 变量提取正则 | `useVariableEditor.ts` | Medium |

### Frontend 测试覆盖问题

| 问题 | 状态 | 优先级 |
|------|------|--------|
| 无 Vitest 配置 | 0 tests | Critical |
| 无 Vue Test Utils | 0 tests | Critical |
| 无 API mock 工具 | 0 tests | High |
| 组件无单元测试 | CreateTask, TaskView, Dashboard | High |
| Composables 无测试 | useVariableEditor | High |

---

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
| `frontend/vitest.config.ts` | Critical |
| `frontend/src/test/setup.ts` | High |
| `frontend/src/test/mocks/api.ts` | High |
| `frontend/src/composables/useVariableEditor.spec.ts` | High |
| `frontend/src/views/CreateTask.spec.ts` | High |
| `frontend/src/views/Dashboard.spec.ts` | High |
| `frontend/src/views/TaskView.spec.ts` | High |

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

Phase 5 (前端测试基础设施 - 3-5天):
  5.1 添加 Vitest + Vue Test Utils 依赖
  5.2 创建 vitest.config.ts
  5.3 创建 test/setup.ts
  5.4 创建 API mock 工具
  5.5 创建 i18n mock

Phase 6 (前端 Composable/工具测试 - 2-3天):
  6.1 useVariableEditor 测试
  6.2 datetime 工具测试

Phase 7 (前端组件测试 - 5-7天):
  7.1 VariableEditor 测试
  7.2 CreateTask 测试
  7.3 Dashboard 测试
  7.4 TaskView 测试

Phase 8 (前端集成测试 - 2-3天):
  8.1 API 层测试
  8.2 Auth 模块测试
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
| Frontend 测试覆盖率 | > 70% | 0% (无测试) |

---

## Phase 5: Frontend 测试基础设施完善

### 5.1 添加测试依赖 (Critical)

**文件:** `frontend/package.json`

**新增依赖:**
```json
{
  "devDependencies": {
    "vitest": "^2.1.0",
    "@vue/test-utils": "^2.4.6",
    "@testing-library/vue": "^8.1.0",
    "jsdom": "^25.0.0",
    "vitest-coverage-v8": "^2.0.0"
  }
}
```

**操作:**
```bash
cd frontend && npm install
```

### 5.2 创建 Vitest 配置 (Critical)

**文件:** `frontend/vitest.config.ts` (新建)

**内容:**
```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/**/*.d.ts', 'src/main.ts', 'src/vite-env.d.ts']
    }
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  }
})
```

### 5.3 创建测试设置文件 (High)

**文件:** `frontend/src/test/setup.ts` (新建)

**内容:**
```typescript
import { cleanup } from '@vue/test-utils'
import { afterEach, vi } from 'vitest'

// Global cleanup after each test
afterEach(() => {
  cleanup()
})

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))
})

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn()
}))

// Mock Element.getBoundingClientRect
Element.prototype.getBoundingClientRect = vi.fn(() => ({
  width: 120,
  height: 120,
  top: 0,
  left: 0,
  bottom: 0,
  right: 0
}))
```

### 5.4 创建 API Mock 工具 (High)

**文件:** `frontend/src/test/mocks/api.ts` (新建)

**内容:**
```typescript
import { vi } from 'vitest'
import type { Task, Project, Branch, PromptTemplate } from '@/api'

// Mock data factories
export const createMockTask = (overrides = {}): Task => ({
  id: 1,
  project_id: 1,
  project_name: 'test-project',
  project_path_with_namespace: 'group/test-project',
  project_url: 'https://gitlab.example.com/group/test-project',
  issue_iid: 42,
  issue_url: 'https://gitlab.example.com/group/test-project/-/issues/42',
  issue_id: 100,
  note_id: null,
  user_prompt: 'Fix the login bug',
  initiator_user_id: 1,
  initiator_gitlab_user_id: 10,
  initiator_username: 'testuser',
  branch_name: 'fix-login-bug',
  branch_url: 'https://gitlab.example.com/group/test-project/-/tree/fix-login-bug',
  merge_request_iid: null,
  merge_request_url: null,
  status: 'pending',
  priority: 1,
  scheduled_at: null,
  container_id: null,
  target_branch: 'main',
  target_branch_url: null,
  commit_sha: null,
  error_message: null,
  additions: 0,
  deletions: 0,
  total_changes: 0,
  input_tokens: null,
  output_tokens: null,
  is_manual: true,
  created_at: '2026-03-31T10:00:00Z',
  updated_at: '2026-03-31T10:00:00Z',
  started_at: null,
  completed_at: null,
  ...overrides
})

export const createMockProject = (overrides = {}): Project => ({
  id: 1,
  name: 'test-project',
  path_with_namespace: 'group/test-project',
  default_branch: 'main',
  ...overrides
})

export const createMockBranch = (overrides = {}): Branch => ({
  name: 'main',
  ...overrides
})

export const createMockPromptTemplate = (overrides = {}): PromptTemplate => ({
  id: 1,
  name: 'Bug Fix Template',
  content: 'Fix the {{issue_type}} in {{file_path}}',
  variable_tips: { issue_type: 'Type of issue (bug, feature, etc.)', file_path: 'Path to the file' },
  is_active: true,
  created_at: '2026-03-31T10:00:00Z',
  updated_at: '2026-03-31T10:00:00Z',
  ...overrides
})

// Mock API functions
export const mockApi = {
  getTasks: vi.fn(),
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
  cancelTask: vi.fn(),
  retryTask: vi.fn(),
  executeTask: vi.fn(),
  rescheduleTask: vi.fn(),
  getProjects: vi.fn(),
  getBranches: vi.fn(),
  createTask: vi.fn(),
  getPromptTemplates: vi.fn(),
  getStats: vi.fn(),
  getConfig: vi.fn(),
  updateConfig: vi.fn()
}

export const setupMockApi = () => {
  return mockApi
}
```

### 5.5 创建 i18n Mock (Medium)

**文件:** `frontend/src/test/mocks/i18n.ts` (新建)

**内容:**
```typescript
import { vi } from 'vitest'

export const mockI18n = {
  t: vi.fn((key: string) => key),
  locale: { value: 'en' }
}

export const createI18nMock = () => mockI18n
```

---

## Phase 6: Frontend 单元测试

### 6.1 测试 useVariableEditor Composable (High)

**文件:** `frontend/src/composables/useVariableEditor.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('useVariableEditor', () => {
  // 变量提取
  describe('extractVariables', () => {
    it('should extract single variable', () => ...)
    it('should extract multiple variables', () => ...)
    it('should ignore empty variable names {{}}', () => ...)
    it('should trim whitespace from variable names', () => ...)
    it('should remove duplicate variables', () => ...)
    it('should return empty array for content without variables', () => ...)
  })

  // Tips 合并
  describe('mergedTips', () => {
    it('should prioritize local tips over template tips', () => ...)
    it('should only include tips for variables in content', () => ...)
    it('should return empty object when no variables', () => ...)
  })

  // 变量重命名检测
  describe('migrateTipsOnRename', () => {
    it('should detect single variable rename', () => ...)
    it('should not migrate when multiple variables change', () => ...)
  })

  // variablesWithTips
  describe('variablesWithTips', () => {
    it('should return array of VariableTip objects', () => ...)
  })
})
```

### 6.2 测试 datetime 工具函数 (Medium)

**文件:** `frontend/src/utils/datetime.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('datetime utilities', () => {
  describe('parseUtcDate', () => {
    it('should parse ISO string with Z suffix', () => ...)
    it('should parse ISO string without Z suffix', () => ...)
    it('should handle Date object', () => ...)
    it('should handle timestamp', () => ...)
  })

  describe('formatDateTimeUtc8', () => {
    it('should format datetime in UTC+8 timezone', () => ...)
    it('should use locale-specific format', () => ...)
  })

  describe('formatDateTimeUtc8Compact', () => {
    it('should format datetime without seconds', () => ...)
  })
})
```

---

## Phase 7: Frontend 组件测试

### 7.1 测试 VariableEditor 组件 (High)

**文件:** `frontend/src/components/VariableEditor.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('VariableEditor', () => {
  // 基础渲染
  it('should render codemirror editor', () => ...)
  it('should display tips panel when variables exist', () => ...)
  it('should show no-variables message when content has no variables', () => ...)

  // 变量高亮
  it('should highlight {{variable}} patterns', () => ...)

  // 工具提示
  it('should show tooltip on variable hover', () => ...)

  // v-model 绑定
  it('should emit update:modelValue on content change', () => ...)
  it('should update editor when modelValue prop changes externally', () => ...)

  // 模板提示
  describe('variableTips prop', () => {
    it('should display tips for variables', () => ...)
    it('should handle editable tips mode', () => ...)
    it('should emit update:variableTips on tip change', () => ...)
  })

  // 清理
  it('should destroy editor on unmount', () => ...)
})
```

### 7.2 测试 CreateTask 组件 (High)

**文件:** `frontend/src/views/CreateTask.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('CreateTask', () => {
  // 基础渲染
  it('should render form with all sections', () => ...)
  it('should show loading state during data fetch', () => ...)

  // 项目选择
  describe('project selection', () => {
    it('should fetch projects on mount', () => ...)
    it('should fetch branches when project changes', () => ...)
    it('should reset branch selection when project changes', () => ...)
    it('should set target branch to project default', () => ...)
  })

  // 分支选择
  describe('branch selection', () => {
    it('should populate branch options from API', () => ...)
    it('should move main to top of target branch options', () => ...)
    it('should clear new branch name when base branch changes', () => ...)
  })

  // 表单验证
  describe('form validation', () => {
    it('should require project selection', () => ...)
    it('should require base branch selection', () => ...)
    it('should require user prompt', () => ...)
    it('should show branch conflict warning', () => ...)
  })

  // 调度选项
  describe('schedule options', () => {
    it('should show delay inputs when delay selected', () => ...)
    it('should show datetime picker when scheduled selected', () => ...)
    it('should calculate delay_seconds correctly', () => ...)
    it('should validate scheduled time is in future', () => ...)
  })

  // Prompt 模板
  describe('prompt templates', () => {
    it('should fetch templates on mount', () => ...)
    it('should apply template on selection', () => ...)
    it('should confirm before overwriting existing prompt', () => ...)
    it('should detect unreplaced variables', () => ...)
  })

  // 提交
  describe('form submission', () => {
    it('should call createTask API on submit', () => ...)
    it('should show success modal on success', () => ...)
    it('should navigate to task view on viewTask', () => ...)
    it('should reset form on createAnother', () => ...)
    it('should show error message on failure', () => ...)
  })

  // 重置
  describe('form reset', () => {
    it('should reset all form values', () => ...)
    it('should clear validation errors', () => ...)
  })
})
```

### 7.3 测试 Dashboard 组件 (High)

**文件:** `frontend/src/views/Dashboard.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('Dashboard', () => {
  // 基础渲染
  it('should render task list', () => ...)
  it('should show loading state', () => ...)
  it('should display summary cards', () => ...)

  // 过滤器
  describe('filters', () => {
    it('should filter by status', () => ...)
    it('should filter by project', () => ...)
    it('should filter by initiator', () => ...)
    it('should refetch tasks when filter changes', () => ...)
  })

  // 自动刷新
  describe('auto-refresh', () => {
    it('should poll every 15 seconds', () => ...)
    it('should skip polling when tab not visible', () => ...)
    it('should clear timer on unmount', () => ...)
  })

  // 任务操作
  describe('task navigation', () => {
    it('should navigate to task view on row click', () => ...)
    it('should not navigate when clicking interactive elements', () => ...)
  })

  // 响应式
  describe('responsive layout', () => {
    it('should show mobile columns on narrow screens', () => ...)
    it('should show desktop columns on wide screens', () => ...)
  })

  // 摘要计算
  describe('summary calculation', () => {
    it('should count total visible tasks', () => ...)
    it('should count running tasks', () => ...)
    it('should count pending/queued tasks', () => ...)
    it('should count completed tasks', () => ...)
  })
})
```

### 7.4 测试 TaskView 组件 (High)

**文件:** `frontend/src/views/TaskView.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('TaskView', () => {
  // 基础渲染
  it('should render task details', () => ...)
  it('should show loading state', () => ...)
  it('should display summary cards', () => ...)

  // 任务操作
  describe('task actions', () => {
    it('should show cancel button for active tasks', () => ...)
    it('should show retry button for failed/cancelled tasks', () => ...)
    it('should show execute button for pending tasks', () => ...)
    it('should show reschedule controls for scheduled tasks', () => ...)
    it('should disable actions based on permissions', () => ...)
  })

  // 操作处理
  describe('action handlers', () => {
    it('should call cancelTask API on cancel', () => ...)
    it('should call retryTask API on retry', () => ...)
    it('should call executeTask API on execute', () => ...)
    it('should call rescheduleTask API on reschedule', () => ...)
    it('should refresh task after action', () => ...)
  })

  // 日志
  describe('logs', () => {
    it('should fetch task logs on mount', () => ...)
    it('should connect to log stream for running tasks', () => ...)
    it('should display logs with ANSI to HTML conversion', () => ...)
    it('should trim large log buffers', () => ...)
  })

  // 自动刷新
  describe('auto-refresh', () => {
    it('should poll every 5 seconds for active tasks', () => ...)
    it('should close log stream on unmount', () => ...)
  })

  // 权限检查
  describe('canManageTask', () => {
    it('should return true for admin users', () => ...)
    it('should return true for task initiator', () => ...)
    it('should return false for non-admin non-initiator', () => ...)
  })
})
```

---

## Phase 8: Frontend 集成测试

### 8.1 API 层测试 (Medium)

**文件:** `frontend/src/api/api.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('API functions', () => {
  // Task APIs
  describe('getTasks', () => {
    it('should call /api/tasks with params', () => ...)
    it('should handle errors gracefully', () => ...)
  })

  describe('getTask', () => {
    it('should call /api/tasks/:id', () => ...)
  })

  describe('createTask', () => {
    it('should POST to /api/tasks with request body', () => ...)
    it('should return created task', () => ...)
  })

  // 认证错误处理
  describe('auth error handling', () => {
    it('should redirect to login on 401', () => ...)
    it('should skip redirect with X-Skip-Auth-Redirect header', () => ...)
  })
})
```

### 8.2 Auth 模块测试 (Medium)

**文件:** `frontend/src/auth.spec.ts` (新建)

**测试覆盖:**
```typescript
describe('auth module', () => {
  describe('initializeAuth', () => {
    it('should fetch auth status on first call', () => ...)
    it('should return cached result on subsequent calls', () => ...)
    it('should handle fetch errors gracefully', () => ...)
  })

  describe('authState', () => {
    it('should have correct initial state', () => ...)
  })

  describe('isAdmin', () => {
    it('should return true for platform_admin role', () => ...)
    it('should return false for other roles', () => ...)
  })

  describe('canAccessSharedPage', () => {
    it('should allow access when OIDC disabled', () => ...)
    it('should allow access for admins', () => ...)
    it('should check page permissions for regular users', () => ...)
  })
})
```

### 8.3 E2E 测试 (pytest-playwright)

**技术选型:** Python pytest-playwright，与现有 backend E2E 测试统一，复用 `backend/tests/e2e/` 基础设施。

**优势:**
- E2E 测试全栈行为 (frontend + backend + db)，与现有 backend E2E 一致
- 复用 `reset_database` fixture 避免状态污染
- 统一运行: `cd backend && pytest tests/e2e/`
- CI/CD 一致: 现有 GitHub Actions 已配置

#### 8.3.1 Dashboard E2E

**文件:** `backend/tests/e2e/tests/test_dashboard.py` (新建)

**测试覆盖:**
- 显示任务列表
- 过滤器交互 (status/project/initiator)
- 任务行点击跳转到详情
- 自动刷新行为
- 摘要卡片显示

#### 8.3.2 CreateTask E2E

**文件:** `backend/tests/e2e/tests/test_create_task.py` (新建)

**测试覆盖:**
- 填写项目/分支/prompt
- 选择调度选项
- 提交表单
- 验证成功提示

#### 8.3.3 TaskView E2E

**文件:** `backend/tests/e2e/tests/test_task_view.py` (新建)

**测试覆盖:**
- 显示任务详情
- cancel/retry/execute 按钮操作
- 日志显示
- 权限检查

---

## Frontend 测试文件清单

### 需要新建的测试文件
| 文件 | 优先级 | 依赖 |
|------|--------|------|
| `frontend/vitest.config.ts` | Critical | - |
| `frontend/src/test/setup.ts` | High | - |
| `frontend/src/test/mocks/api.ts` | High | - |
| `frontend/src/test/mocks/i18n.ts` | Medium | - |
| `frontend/src/composables/useVariableEditor.spec.ts` | High | setup.ts |
| `frontend/src/utils/datetime.spec.ts` | Medium | setup.ts |
| `frontend/src/components/VariableEditor.spec.ts` | High | setup.ts, mocks |
| `frontend/src/views/CreateTask.spec.ts` | High | setup.ts, mocks |
| `frontend/src/views/Dashboard.spec.ts` | High | setup.ts, mocks |
| `frontend/src/views/TaskView.spec.ts` | High | setup.ts, mocks |
| `frontend/src/api/api.spec.ts` | Medium | setup.ts |
| `frontend/src/auth.spec.ts` | Medium | setup.ts |
| `backend/tests/e2e/tests/test_dashboard.py` | High | conftest.py |
| `backend/tests/e2e/tests/test_create_task.py` | High | conftest.py |
| `backend/tests/e2e/tests/test_task_view.py` | High | conftest.py |

---

## Frontend 验证方式

```bash
# 1. 安装测试依赖
cd frontend && npm install

# 2. 运行所有前端测试
cd frontend && npx vitest run

# 3. 运行测试并查看覆盖率
cd frontend && npx vitest run --coverage

# 4. 运行测试并监听变化 (开发模式)
cd frontend && npx vitest

# 5. 运行特定测试文件
cd frontend && npx vitest run src/views/CreateTask.spec.ts

# 6. 运行包含特定名称的测试
cd frontend && npx vitest run -t "should fetch projects"
```

---

## Frontend 实施顺序

```
Phase 5 (测试基础设施 - 3-5天):
  5.1 添加测试依赖
  5.2 创建 Vitest 配置
  5.3 创建测试设置文件
  5.4 创建 API Mock 工具
  5.5 创建 i18n Mock

Phase 6 (Composable/工具测试 - 2-3天):
  6.1 测试 useVariableEditor
  6.2 测试 datetime 工具

Phase 7 (组件测试 - 5-7天):
  7.1 测试 VariableEditor
  7.2 测试 CreateTask
  7.3 测试 Dashboard
  7.4 测试 TaskView

Phase 8 (集成测试 - 2-3天):
  8.1 API 层测试
  8.2 Auth 模块测试
  8.3 E2E 测试 (pytest-playwright)
    8.3.1 Dashboard E2E
    8.3.2 CreateTask E2E
    8.3.3 TaskView E2E
```

---

## Frontend 风险评估

| 变更 | 风险 | 缓解措施 |
|------|------|----------|
| 添加测试依赖 | 低 | Vitest 是成熟框架 |
| 组件测试 | 中 | 使用 Vue Test Utils 隔离组件 |
| Mock API | 低 | 创建可复用的 mock 工厂 |
| 定时器测试 | 中 | 使用 fake timers |
| EventSource 测试 | 高 | 条件导入，JSDOM 不支持时跳过 |
