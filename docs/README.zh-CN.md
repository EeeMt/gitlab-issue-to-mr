# Codify

[English README](../README.md)

Codify 帮你把需求变成代码。写清楚目标和约束，剩下的交给 Codify——在隔离容器里运行 AI Harness（Claude / Codex）生成代码、推送提交、开 MR。

通过预约调度，让 AI 全天候运转，充分利用时间和算力资源。整个过程在 Dashboard 里一目了然。

## 从需求到代码，三步搞定

1. **写需求** — 描述要解决的问题和期望结果
2. **发起任务** — 立即执行，或预约到空闲时段，让资源不闲置
3. **查看结果** — 跟踪状态、翻阅日志、检查交付物

## 幕后发生了什么

当你发起一个任务后，Codify 会：

1. 按优先级和预约时间排入调度队列，遵守并发限制
2. 启动一个独立的 Docker 容器
3. 在容器里克隆仓库、运行 Harness（Claude CLI / Codex CLI）生成代码
4. 把改动提交、推送到新分支，创建或更新 MR
5. 全程在 Dashboard 记录日志和状态变化

## 关键组件

- `backend/app/api/tasks.py` — 任务 API 与队列视图
- `backend/app/api/issues.py` — 需求管理 API
- `backend/app/core/worker.py` — 任务执行与 MR 更新
- `backend/app/scheduler.py` — 优先级调度与崩溃恢复
- `backend/app/api/config.py` — 运行时与认证配置
- `frontend/src/views/` — Dashboard 页面
- `deploy/` — Dockerfile、Compose、Worker 启动脚本

## Dashboard 一览

| 页面 | 用途 |
|------|------|
| **工作区** | |
| 仪表盘 | 概览、热力图、趋势 |
| 需求 | 需求列表与详情 |
| &ensp;↳ 创建需求 | 用提示词模板快速描述需求 |
| 任务 | 任务列表与详情，含实时日志 |
| &ensp;↳ 创建任务 | 手动配置并发起任务 |
| 会话管理 | 查看和管理登录会话 |
| **洞察** | |
| 统计分析 | 执行趋势与成功率、AI Provider 维度对比 |
| 调度总览 | 未来 24h 排程密度分布 |
| 监控 | 队列看板、执行时间线、健康检查 |
| **管理** | |
| 访问管理 | 用户、角色与状态管理 |
| 用量管理 | 用户 Token / 任务数配额 |
| 系统统计 | 系统生命周期统计（管理员） |
| 系统配置 | 运行时参数和集成配置 |
| &ensp;↳ OIDC 诊断 | 调试 SSO 登录问题 |

## 快速开始

### 你需要

- Docker 与 Docker Compose
- 一个可访问的 GitLab 实例
- 一个兼容 Harness 的模型服务端点（Claude → Anthropic 协议，Codex → OpenAI 协议）

### 1. 填写配置

`deploy/docker-compose.yml` 默认从 `deploy/.env.test` 读取环境变量，至少填好这几项：

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`
- `ANTHROPIC_API_KEY`（或通过 Dashboard 配置 AI Provider）

小贴士：

- 运行时覆盖配置会持久化到 PostgreSQL 的 `system_config`
- 在 Dashboard 中录入的敏感配置会加密存储
- 如果 PostgreSQL volume 被删除，运行时配置、用户、会话和认证状态都会丢失

### 2. 一键启动

```bash
cd deploy
docker-compose up -d --build
```

默认端口：

- 前端：`http://localhost:8880`
- 后端 API：`http://localhost:8000`

### 3. 配置登录（推荐）

首次部署建议先跳过 OIDC，跑通基本流程后再开启。详见 [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)。

推荐步骤：

1. 先保持 OIDC 关闭，确认服务正常运行
2. 确保 `CONFIG_ENCRYPTION_KEY` 已设置
3. 在 Dashboard → 系统配置 页面填写 OIDC 参数
4. 验证通过后再启用

---

## Dashboard 使用指南

### 登录

系统支持两种认证方式：

**GitLab OIDC 登录（推荐）**
- 点击登录页面的"使用 GitLab 登录"按钮
- 跳转到 GitLab 授权页面完成认证
- 首次登录后管理员可在"访问管理"中调整用户角色

**本地账号登录**
- 管理员在系统初始化时创建本地账号，或通过"访问管理"添加
- 未启用 OIDC 时使用本地账号登录

### 需求管理

页面路由：`/issues`

在需求页面创建和管理需求（Issue）：
- 点击「创建需求」描述目标、选择项目
- 可使用提示词模板快速填写
- 可设置默认 Harness 与默认 Worker Profile
- 从需求详情页可直接发起任务

### 任务列表

任务列表页（`/tasks`）以表格展示任务队列，顶部为统计卡；首页（`/dashboard`）为工作台总览。

**筛选与排序：**
- 按项目、发起人、任务状态、优先级、Harness 筛选
- 服务端排序、列显隐、关键字搜索、快速过滤"我的"
- 远程分页

**任务行信息：**
- 任务 ID、项目名、Issue 链接
- 执行状态（颜色标签）与 Harness 引擎
- 代码变更量（`+添加 -删除`）
- 创建时间 / 计划时间

优先级仍为 P0 / P1 / P2 三级（见下方说明），从固定标签页改成了可筛选、可排序的表格列。

### 任务详情

点击任意任务进入详情页（`/tasks/:id`）。

**基础信息面板：**

| 字段 | 说明 |
|------|------|
| 项目 | 所属 GitLab 项目 |
| Issue | 关联的 GitLab Issue（可点击跳转） |
| 分支 | 生成代码所用的分支（可点击跳转） |
| 基础分支 | 分支基于哪个分支创建 |
| 目标分支 | MR 的合并目标 |
| MR URL | 创建的 Merge Request 链接 |
| 代码变更 | `+N -M (共K行)` |
| **Token 用量** | 本次 Harness 调用的输入/输出 token 数 |
| Harness | 执行引擎（Claude / Codex） |
| 容器 ID | 执行本任务的 Docker 容器 ID |
| 创建时间 | 任务创建时间 |
| 开始时间 | 容器开始执行时间 |
| 完成时间 | 执行结束时间 |

**操作按钮：**

| 按钮 | 可用状态 | 功能 |
|------|---------|------|
| 立即执行 | PENDING | 跳过等待，立即触发执行 |
| 取消 | PENDING / QUEUED / RUNNING | 取消任务，状态变为 CANCELLED |
| 重试 | FAILED / CANCELLED | 复制原任务冻结的 Harness/端点/凭据重新入队 |
| 重新调度 | PENDING（有计划时间） | 修改计划执行时间 |
| 编辑 | — | 修改任务配置 |
| 下载运行归档 | — | 下载任务运行时归档（事件、日志、制品） |
| 强制标记 | — | 强制标记为完成/失败，需填写原因 |

**日志面板：**
- 展示容器执行日志，支持 **ANSI 颜色**渲染
- 完整显示 emoji（如 ✅ ❌ 🔧 等）
- 任务执行中每约 10 秒自动刷新一次

### 创建任务

页面路由：`/issues/create`（旧路径 `/create-task` 已重定向到此）。

任务统一从 Issue 发起：在 Issue 详情页点击「创建任务/追加任务」打开创建抽屉，也可以在创建 Issue 时直接填写。抽屉字段：

| 字段 | 说明 |
|------|------|
| 提示词 | 发给 Harness 的完整提示词，可从模板库选择（支持标签过滤） |
| 模式 | execute（实施）/ plan（分析），可勾选"仅当有变更才提交" |
| 会话续接 | fresh（新会话）/ continue（续接 Issue 既有会话） |
| AI Provider | 选择模型提供方（默认使用 Issue 级设置） |
| Harness | Claude（Codex 适配器已接入，灰度中；受 Issue 现有会话 lineage 约束） |
| 调度方式 | 立即执行，或定时执行（带 slot 容量热力图与容量校验） |
| 运行指令模板 | 可选择模板并实时预览渲染结果 |
| 技能 | 按需启用已上传的技能 |

> 任务创建时冻结不可变 Worker/Provider 快照，后续修改配置不会影响已创建的任务。

### 调度总览

页面路由：`/schedule-overview`

展示未来 24 小时按小时分桶的排程密度柱状图：
- 可点击时间窗口查看详情
- 支持"仅看我的任务"

### 监控页面

页面路由：`/monitor`（需 monitor 页面权限）

三个页签：
- **runtime** — 队列看板（运行中 / 就绪 / 等待 / 被前序任务阻塞）与执行时间线
- **debug** — 活跃 Worker 容器列表与容器日志
- **health** — 健康检查：队列积压、运行中缺容器、孤儿容器、24h 失败数、Docker 目标可达性

### 统计分析

页面路由：`/analytics`

提供系统运行的统计视图：
- 任务数量趋势（按天/按状态）
- 代码变更量趋势（添加 / 删除行数）
- 成功率、平均执行时长
- 按项目、发起人、Harness 的任务分布

### 配置管理

页面路由：`/configuration`（仅管理员）

分为 11 个标签页：运行时配置、认证（Auth/OIDC）、GitLab 连接、AI Providers、Prompt 模板、Worker、Skills、Mattermost 通知、公告横幅、维护、Webhook 事件。

#### 运行时配置（Runtime）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 最大并发数 | 同时运行的 Worker 容器数量上限 | 3 |
| 任务超时（秒） | 单个任务最长执行时间 | 1800（30分钟） |
| 最大重试次数 | 任务失败后自动重试的次数 | 0 |
| 调度间隔（秒） | 调度器轮询新任务的间隔 | 5 |
| 默认目标分支 | MR 的默认合并目标分支 | main |
| Max Turns（最大对话轮数） | Claude 的最大对话轮数（Codex 不支持） | 20 |

> Max Turns 越大，Claude 可以执行更多工具调用轮次，解决更复杂的任务；但也会消耗更多 token 和时间。

#### Worker 配置

管理员可以在系统配置中维护多个 Worker 配置（Worker Profile）。每个配置包含镜像、挂载、环境变量、启用的 Harness、运行前/运行后脚本和运行指令模板。

需求可以设置默认 Worker 和默认 AI Provider。新任务默认使用需求级设置，也可以在创建任务时覆盖。任务创建后会保存 Worker/Harness 快照，后续修改 Worker 配置不会影响已经创建的任务。

#### AI Provider

管理员可以配置多个 AI Provider，每个 Provider 绑定一种 Harness 协议：

| 配置项 | 说明 |
|--------|------|
| Provider 类型 | `anthropic-messages`（Claude）或 `openai-responses`（Codex） |
| 模型 | 使用的模型名称（由 Provider 决定） |
| Base URL | API 端点地址 |
| 凭据 | 独立管理的模型凭据（加密存储，可轮换/退役） |

#### 认证配置（Auth）

配置 GitLab OIDC 登录：

| 配置项 | 说明 |
|--------|------|
| OIDC 启用 | 是否开启 OIDC 登录验证 |
| GitLab URL | GitLab 实例地址 |
| Client ID | GitLab OAuth 应用的 Client ID |
| Client Secret | GitLab OAuth 应用的 Client Secret |
| 默认角色 | 首次登录用户的默认权限角色 |
| 允许所有 GitLab 用户 | 是否允许所有 GitLab 用户登录 |

详细配置步骤见 [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)。

#### 集成配置（Integration）

| 配置项 | 说明 |
|--------|------|
| GitLab URL | GitLab 实例地址 |
| GitLab Bot Token | Bot 账号的 Personal Access Token |

#### Prompt 模板

维护提示词模板库，创建任务时从模板抽屉中选择（支持标签过滤与覆盖确认）。

#### Skills（技能目录）

管理员上传/管理全局技能包（zip 导入），任务按需启用；技能随 Worker Profile 解析，并在任务快照中冻结版本。

#### Mattermost 通知

配置 Mattermost 集成，任务完成/失败事件推送通知；支持通知 Profile 与渠道目标配置。

#### 公告横幅

设置系统级公告横幅，展示在 Dashboard 顶部。

#### 维护

系统数据清理（已删除 Issue/Task 的归档、workspace、容器，支持 force）与运行时配置重置。

#### Webhook 事件

查看 GitLab webhook 接收的事件日志（可审计）。

### 访问管理

页面路由：`/access-management`（仅管理员）

管理已登录用户的权限：

| 角色 | 权限说明 |
|------|---------|
| platform_admin | 完全访问，包括配置、日志、容器监控 |
| platform_user | 查看/创建任务，不可访问管理配置页；Monitor、Analytics、调度总览为按角色分配的页面权限 |

---

## 任务优先级说明

| 优先级 | 值 | 典型使用场景 |
|--------|---|------------|
| P0 | 0 | 紧急修复、生产环境问题 |
| P1 | 1 | 常规功能开发 |
| P2 | 2 | 低优先级、后台任务 |

调度器按 **P0 → P1 → P2** 顺序出队，相同优先级按创建时间先后排序。创建任务时可自由选择优先级。

---

## 任务状态说明

| 状态 | 颜色 | 说明 |
|------|------|------|
| PENDING | 灰色 | 已创建，等待调度 |
| QUEUED | 蓝色 | 已被调度器选中，即将执行 |
| RUNNING | 蓝色（活动） | Worker 容器正在执行 |
| COMPLETED | 绿色 | 成功完成，MR 已创建 |
| FAILED | 红色 | 执行失败（Harness 出错 / 超时 / 代码提交失败等） |
| CANCELLED | 灰色 | 被用户手动取消 |

---

## 配置项参考

以下环境变量在部署时配置（`deploy/.env` 或 Docker Compose 环境变量）：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `GITLAB_URL` | GitLab 实例地址 | `https://gitlab.example.com` |
| `GITLAB_BOT_TOKEN` | Bot 账号 PAT（`api` 权限） | `glpat-xxxx` |
| `ANTHROPIC_BASE_URL` | 默认 AI Provider（Claude）端点 | `https://api.anthropic.com` |
| `ANTHROPIC_API_KEY` | 默认 AI Provider（Claude）密钥 | `sk-ant-xxxx` |
| `ANTHROPIC_MODEL` | 默认模型（多 Provider 场景以 Dashboard 配置为准） | `claude-sonnet-4-20250514` |
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://...` |
| `DOCKER_HOST` | Docker 引擎地址 | `tcp://localhost:2376` |
| `WORKER_IMAGE` | Worker 容器镜像 | `codify-worker/java21-maven:2026.07` |
| `MAX_CONCURRENCY` | 最大并发 Worker 数 | `3` |
| `TASK_TIMEOUT` | 任务超时秒数 | `1800` |
| `DEFAULT_TARGET_BRANCH` | 默认 MR 目标分支 | `main` |
| `CONFIG_ENCRYPTION_KEY` | 配置加密密钥 | 32 字节 base64 |
| `AUTO_MIGRATE` | 启动时是否自动执行数据库迁移 | `true` |

> 运行时配置（并发数、超时、Max Turns、AI Provider 等）也可以通过 Dashboard 配置页面动态修改，无需重启服务。

---

## 常用命令

运行 `make help` 查看所有可用命令。

### 后端

```bash
cd backend && pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && pytest
```

### 前端

```bash
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run build
```

### 重建部署镜像

```bash
# backend / scheduler
docker build -f deploy/Dockerfile.backend -t codify-backend:latest .
cd deploy && docker-compose up -d backend scheduler

# frontend / nginx
docker build -f deploy/Dockerfile.frontend -t codify-nginx:latest .
cd deploy && docker-compose up -d --build nginx

# worker
docker build -f deploy/Dockerfile.worker-java21-maven -t codify-worker/java21-maven:2026.07 .
```

---

## 运维备忘

- `deploy/docker-compose.yml` 中，`backend` 和 `scheduler` 共用同一个 backend 镜像
- 默认 Compose 中，`backend` 与 `scheduler` 均使用 `AUTO_MIGRATE=true`（启动时自动执行迁移）
- 配置页面路由为 `/configuration`
- 认证用户能看到的项目和任务会按 GitLab 权限过滤

---

## 常见问题

**Q: 任务显示 FAILED，如何排查？**

1. 打开任务详情页，查看**日志面板**的完整输出（支持颜色，ANSI 格式）
2. 关注 `❌ Error` 行和最后的 `Exit code` 信息
3. 常见原因：
   - AI Provider 超额或网络不通
   - 代码语法错误导致测试失败
   - 仓库权限不足（无法推送分支）
   - 任务超时（默认 30 分钟，可在配置页调整）

---

**Q: 如何调整任务的工作深度（Max Turns）？**

进入 **Configuration → 运行时配置**，修改 **Max Turns** 字段（范围 1–1000）。

- 增大 Max Turns：Claude 可以执行更多工具调用，适合复杂任务
- 减小 Max Turns：更快返回结果，适合简单任务，节省 token

> Codex Harness 不支持 Max Turns，该字段仅对 Claude 生效。

---

**Q: 如何查看 token 消耗？**

在任务详情页的**基础信息**面板中，"Token 用量"行显示本次调用的输入/输出 token 数。

- **输入（Input）**：包含系统提示、上下文、工具定义
- **输出（Output）**：Harness 生成的文本和工具调用

历史任务（在 token 统计功能上线前创建的任务）不显示此字段（显示 `-`）。

---

**Q: 多个任务同时触发会怎样？**

调度器维护一个**并发上限**（默认 3，可配置）。超过上限的任务进入队列等待。

此外，系统对**同一个 Issue 的并发任务**有互斥保护：同一 Issue 下不会同时运行两个任务，后来的任务会等待前一个完成后再执行。

---

**Q: Worker 容器命名规则是什么？**

每个 Worker 容器的命名格式为：

```
codify-{task_id}-p{project_id}-i{issue_iid}
```

例如：`codify-42-p7-i15`，表示任务 #42，项目 ID 7，Issue #15。

手动任务（无 Issue）中 `issue_iid` 部分为 `iNone`。

---

**Q: 日志中的颜色和 emoji 不显示？**

请确认使用的是最新部署版本。Codify 支持 ANSI 颜色渲染和 emoji 显示，旧版本日志以纯文本格式存储，升级后的新任务日志将正常显示颜色和 emoji。

---

## 相关文档

- [English README](../README.md)
- [文档索引](README.md)
- [DEPLOYMENT.md](DEPLOYMENT.md) — 详细部署指南
- [DEVELOPMENT.md](DEVELOPMENT.md) — 开发环境搭建
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md) — GitLab OIDC 登录配置
- [TESTING.md](TESTING.md) — 测试指南
- [../deploy/offline-bundle/README.md](../deploy/offline-bundle/README.md) — 离线部署

## License

MIT
