# 重构进度跟踪

## 总体进度

| Priority | Phase | 状态 | 开始日期 | 完成日期 |
|----------|-------|------|---------|----------|
| P0 | Bug 修复 | Pending | - | - |
| P1 | 基础测试建设 | Pending | - | - |
| Phase 1 | 模块划分优化 | Pending | - | - |
| Phase 2 | 代码质量提升 | Pending | - | - |
| Phase 3 | 测试基础设施完善 | Pending | - | - |
| Phase 4 | 稳定性增强 | Pending | - | - |

---

## P0: Critical Bug 修复

### 任务清单

- [x] 2.1 修复 bare `except:` bug (Critical)
  - [x] `docker_client.py:135` - 添加 `Exception as e`

### 完成记录

#### 2026-03-31 修复 bare except bug

**完成**
- [x] `docker_client.py:135` - 将 `except:` 改为 `except Exception as inner_e:`
- [x] 修复后 `inner_e` 正确捕获内部异常，不再使用外部的 `e`
- [x] 新增测试覆盖: `test_docker_client.py` (12 个测试)

**测试验证**
- 单元测试: ✅ 12 passed (test_docker_client.py)
- 原有单元测试: ✅ 146 passed (无新失败)

**变更分析**
- 文件改动: 2 个
  - `backend/app/core/docker_client.py` (bug fix)
  - `backend/tests/unit/test_docker_client.py` (新增)
- 新增行数: +220 (测试文件)
- 删除行数: -1

**遗留问题 / 后续待办**
- 无

---

## P1: 基础测试建设

### 任务清单

- [ ] 3.1 创建共享 `conftest.py`
  - [ ] `mock_settings` fixture
  - [ ] `mock_db_session` fixture
  - [ ] `clean_singletons` fixture

- [x] 3.2 添加 DockerClientWrapper 单元测试 (已实施)
  - [x] `test_docker_client.py` - 12 个测试
  - [x] 覆盖 pull_image, create_container, wait_for_container, remove_container, get_container_logs

- [ ] 1.3 移动错误放置的代码
  - [ ] 移动 `build_enhanced_prompt()` 到 parser.py
  - [ ] 移动 `build_prompt_with_issue_context()` 到 parser.py
  - [ ] 更新 imports

- [ ] 1.4 消除重复代码
  - [ ] 删除 `scheduler.py` 中的 `get_settings()` wrapper
  - [ ] 删除 `worker.py` 中的 `get_settings()` wrapper
  - [ ] 提取 `_build_project_lookup()` 到共享模块
  - [ ] 更新相关 imports

---

## Phase 1: 模块划分优化

### 任务清单

- [ ] 1.1 拆分 `api/config.py`
  - [ ] 1.1.1 创建 `api/oidc.py` (最独立，先拆)
  - [ ] 1.1.2 创建 `api/project_webhooks.py`
  - [ ] 1.1.3 创建 `api/mattermost.py`
  - [ ] 1.1.4 保留 `api/config.py` 仅含 Runtime config
  - [ ] 更新路由注册
  - [ ] 更新 imports

- [ ] 1.2 拆分 `core/worker.py`
  - [ ] 提取 `_create_mr_if_needed()`
  - [ ] 提取 `_build_container_env()`
  - [ ] 提取 `_process_task_result()`
  - [ ] 提取 `_send_notifications()`
  - [ ] 提取 `_update_mr_description()`
  - [ ] 验证功能不变

- [ ] 1.5 拆分 `api/tasks.py`
  - [ ] 提取 `_build_project_lookup()` 到 `core/projects.py`
  - [ ] 简化验证逻辑
  - [ ] 验证功能不变

---

## Phase 2: 代码质量提升

### 任务清单

- [ ] 2.2 修复 async 中使用同步 requests
  - [ ] `worker.py:789-795` - 改用 httpx.AsyncClient (先试点)
  - [ ] `gitlab_client.py:217-224` - 改用 httpx.AsyncClient

- [ ] 2.3 添加类型注解
  - [ ] `scheduler.py` - `get_settings()` 返回类型
  - [ ] `worker.py` - `get_settings()` 返回类型
  - [ ] `docker_client.py` - Container 参数类型

- [ ] 2.4 简化深度嵌套代码
  - [ ] `worker.py:330-365` - MR 创建逻辑重构

---

## Phase 3: 测试基础设施完善

### 任务清单

- [x] 3.2 添加 DockerClientWrapper 测试 (已完成)
  - [x] `pull_image()` 测试
  - [x] `create_container()` 测试
  - [x] `wait_for_container()` 测试
  - [x] `remove_container()` 测试
  - [x] `get_container_logs()` 测试

- [ ] 3.3 修复 Print-Based 测试
  - [ ] `test_webhook.py` - 转换为 pytest 断言

- [ ] 3.4 添加 API Endpoint 测试
  - [ ] `test_containers_api.py` 新建
  - [ ] `test_stats_api.py` 新建

- [ ] 3.5 改进 E2E 测试覆盖
  - [ ] `test_task_queue.py` 新建
  - [ ] `test_task_details.py` 新建
  - [ ] `test_manual_task.py` 新建

---

## Phase 4: 稳定性增强

### 任务清单

- [ ] 4.1 添加敏感数据清理测试
  - [ ] `test_scrubbing.py` 新建
  - [ ] `scrub_sensitive_data()` 测试
  - [ ] `sanitize_sensitive_data()` 测试

- [ ] 4.2 添加 Scheduler 核心逻辑测试
  - [ ] Priority queue ordering 测试
  - [ ] Issue mutex behavior 测试
  - [ ] Concurrency limiting 测试

- [ ] 4.3 添加 GitLab Client 重试测试
  - [ ] API 错误处理测试
  - [ ] 超时行为测试
  - [ ] Rate limit 响应测试

---

## 变更记录

<!-- 每次重构后在此记录 -->

## 成果统计

| 指标 | 目标 | 当前 |
|------|------|------|
| 代码行数 (config.py) | < 400 | 1441 |
| 代码行数 (worker.py) | < 500 | 824 |
| 代码行数 (tasks.py) | < 500 | 860 |
| 测试覆盖率 | > 80% | ~45% (需确认) |
| 类型注解完整度 | 100% | - |
| Critical bugs | 0 | 1 (bare except) |
