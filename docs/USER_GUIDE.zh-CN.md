# GIMR 使用说明

> GitLab Issue to MR Bot — AI 驱动的自动化代码生成与 Merge Request 创建服务

---

## 目录

1. [产品概述](#1-产品概述)
2. [工作流程](#2-工作流程)
3. [通过 GitLab Issue 触发任务](#3-通过-gitlab-issue-触发任务)
4. [Dashboard 使用指南](#4-dashboard-使用指南)
   - 4.1 [登录](#41-登录)
   - 4.2 [任务列表](#42-任务列表)
   - 4.3 [任务详情](#43-任务详情)
   - 4.4 [手动创建任务](#44-手动创建任务)
   - 4.5 [调度总览](#45-调度总览)
   - 4.6 [监控页面](#46-监控页面)
   - 4.7 [统计分析](#47-统计分析)
   - 4.8 [配置管理](#48-配置管理)
   - 4.9 [访问管理](#49-访问管理)
5. [任务优先级说明](#5-任务优先级说明)
6. [任务状态说明](#6-任务状态说明)
7. [配置项参考](#7-配置项参考)
8. [常见问题](#8-常见问题)

---

## 1. 产品概述

GIMR（GitLab Issue to MR Bot）是一个 AI 驱动的代码生成服务，核心能力如下：

- 监听 GitLab Issue 评论，识别 `@ai-bot <需求>` 指令
- 将每条需求封装为**任务（Task）**，按优先级调度执行
- 在隔离的 Docker 容器中运行 Claude CLI 生成代码
- 自动完成：创建分支 → 生成代码 → 提交 → 推送 → 发起 Merge Request
- 将执行结果（MR 链接、错误信息）回写到 GitLab Issue 评论
- 提供 Web Dashboard 供管理员和用户查看任务状态、日志、统计信息

---

## 2. 工作流程

```
GitLab Issue 评论 "@ai-bot 需求"
        │
        ▼
  Webhook 接收（/api/webhook/gitlab）
        │
        ▼
  创建 Task（状态: PENDING）
        │
        ▼
  调度器（Scheduler）按优先级 + 并发限制调度
        │
        ▼
  启动 Worker 容器（状态: RUNNING）
  ┌──────────────────────────────┐
  │  克隆仓库到 /workspace        │
  │  运行 ci-claude.sh           │
  │    └─ Claude CLI (stream-json)│
  │  git add + commit + push     │
  │  调用 GitLab API 创建 MR      │
  │  打印 GIMR_STATS（token 用量）│
  └──────────────────────────────┘
        │
        ▼
  更新 Task（状态: COMPLETED / FAILED）
  存储：MR URL、token 用量、代码变更量
        │
        ▼
  在 GitLab Issue 发表评论（MR 链接 / 错误摘要）
```

---

## 3. 通过 GitLab Issue 触发任务

### 3.1 基本用法

在任意 GitLab Issue 的**评论**中输入：

```
@ai-bot <你的需求描述>
```

示例：

```
@ai-bot 在 src/utils/math.py 中实现一个快速排序函数，并添加单元测试
```

```
@ai-bot 修复用户登录时如果邮箱包含大写字母导致的 404 问题
```

### 3.2 触发条件

- 评论必须包含 `@ai-bot`（大小写不敏感）
- Webhook 需要已正确配置（见 [GITLAB_WEBHOOK_SETUP.md](GITLAB_WEBHOOK_SETUP.md)）
- Bot 账号需要对目标项目有 Developer 及以上权限

### 3.3 执行反馈

任务创建后，Bot 会在 Issue 中：

1. **开始时**（可选）：发帖说明任务已接受
2. **完成后**：发帖附上 Merge Request 链接
3. **失败时**：发帖附上错误摘要

示例回复：

```
✅ 代码已生成，Merge Request 已创建：
https://gitlab.example.com/mygroup/myproject/-/merge_requests/42
```

### 3.4 指定基础分支（Base Branch）

如需在特定分支上开发，可在评论中注明：

```
@ai-bot 基于 feature/v2 分支，实现新的缓存层
```

系统会尽可能根据上下文推断，或使用配置的默认目标分支。

---

## 4. Dashboard 使用指南

访问地址：`http://<部署主机>:8880`（默认端口）

### 4.1 登录

系统支持两种认证方式：

**GitLab OIDC 登录（推荐）**
- 点击登录页面的"使用 GitLab 登录"按钮
- 跳转到 GitLab 授权页面完成认证
- 首次登录后管理员可在"访问管理"中调整用户角色

**无认证模式**
- 若管理员未启用 OIDC，直接访问 Dashboard 即可（无鉴权）
- 仅适合内网私有部署

### 4.2 任务列表

主页（`/`）展示任务队列，按优先级分为三个标签页：

| 标签 | 优先级值 | 说明 |
|------|---------|------|
| P0   | 0       | 最高优先级，最先被调度 |
| P1   | 1       | 普通优先级 |
| P2   | 2       | 低优先级 |

**筛选功能：**
- 按项目筛选
- 按发起人筛选
- 按任务状态筛选

**任务卡片信息：**
- 任务 ID、项目名、Issue 链接
- 执行状态（颜色标签）
- 代码变更量（`+添加 -删除`）
- 创建时间 / 计划时间

### 4.3 任务详情

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
| **Token 用量** | 本次 Claude 调用的输入/输出 token 数 |
| 容器 ID | 执行本任务的 Docker 容器 ID |
| 创建时间 | 任务创建时间 |
| 开始时间 | 容器开始执行时间 |
| 完成时间 | 执行结束时间 |

**操作按钮：**

| 按钮 | 可用状态 | 功能 |
|------|---------|------|
| 立即执行 | PENDING | 跳过等待，立即触发执行 |
| 取消 | PENDING / QUEUED | 取消任务，状态变为 CANCELLED |
| 重试 | FAILED / CANCELLED | 重新加入队列 |
| 重新调度 | PENDING（有计划时间） | 修改计划执行时间 |

**日志面板：**
- 展示容器执行日志，支持 **ANSI 颜色**渲染
- 完整显示 emoji（如 Claude 的 ✅ ❌ 🔧 等）
- 任务执行中每约 10 秒自动刷新一次

### 4.4 手动创建任务

页面路由：`/create-task`，或点击侧边栏"创建任务"。

不依赖 GitLab Issue，直接输入参数创建任务：

| 字段 | 说明 |
|------|------|
| 项目 | 从下拉列表选择目标 GitLab 项目 |
| 需求描述 | 发给 Claude 的完整提示词 |
| 基础分支 | 在哪个分支上开发（可选，默认 main） |
| 目标分支 | MR 合并到哪个分支（可选，默认 main） |
| 优先级 | P0 / P1 / P2 |
| 计划时间 | 延迟到指定时间再执行（可选） |

> 手动任务不会向 GitLab Issue 发送评论通知。

### 4.5 调度总览

页面路由：`/schedule`

展示未来调度队列的可视化视图：
- 待执行任务的计划时间分布
- 当前正在运行的任务

### 4.6 监控页面

页面路由：`/monitor`

展示系统运行状态：
- 当前活跃的 Worker 容器列表
- 每个容器的任务 ID、运行时长、项目信息
- 实时容器日志查看（仅管理员）

### 4.7 统计分析

页面路由：`/analytics`

提供系统运行的统计视图：
- 任务数量趋势（按天/按状态）
- 代码变更量趋势（添加 / 删除行数）
- 成功率、平均执行时长
- 按项目、发起人的任务分布

### 4.8 配置管理

页面路由：`/configuration`（仅管理员）

分为以下几个标签页：

#### 运行时配置（Runtime）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 最大并发数 | 同时运行的 Worker 容器数量上限 | 3 |
| 任务超时（秒） | 单个任务最长执行时间 | 1800（30分钟） |
| 最大重试次数 | 任务失败后自动重试的次数 | 0 |
| 调度间隔（秒） | 调度器轮询新任务的间隔 | 5 |
| 默认目标分支 | MR 的默认合并目标分支 | main |
| **Claude Max Turns** | Claude CLI 的最大对话轮数 | 20 |
| Anthropic 模型 | 使用的 Claude 模型名称 | claude-opus-4-5 |
| Anthropic Base URL | API 端点地址 | （见部署配置） |

> Claude Max Turns 越大，Claude 可以执行更多工具调用轮次，解决更复杂的任务；但也会消耗更多 token 和时间。

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

#### Webhook 配置

展示各项目的 Webhook 配置状态：
- **已配置**：Webhook 存在且 Secret 匹配
- **需关注**：Webhook 存在但配置可能不一致
- **缺失**：项目尚未配置 Webhook
- 支持直接在 Dashboard 中为项目创建/更新 Webhook

### 4.9 访问管理

页面路由：`/access`（仅管理员）

管理已登录用户的权限：

| 角色 | 权限说明 |
|------|---------|
| admin | 完全访问，包括配置、日志、容器监控 |
| platform_user | 查看任务、创建手动任务，不可访问配置页面 |

---

## 5. 任务优先级说明

| 优先级 | 值 | 典型使用场景 |
|--------|---|------------|
| P0 | 0 | 紧急修复、生产环境问题 |
| P1 | 1 | 常规功能开发 |
| P2 | 2 | 低优先级、后台任务 |

调度器按 **P0 → P1 → P2** 顺序出队，相同优先级按创建时间先后排序。

通过 GitLab Issue 触发的任务默认为 P1，手动创建任务时可自由选择优先级。

---

## 6. 任务状态说明

| 状态 | 颜色 | 说明 |
|------|------|------|
| PENDING | 灰色 | 已创建，等待调度 |
| QUEUED | 蓝色 | 已被调度器选中，即将执行 |
| RUNNING | 蓝色（活动） | Worker 容器正在执行 |
| COMPLETED | 绿色 | 成功完成，MR 已创建 |
| FAILED | 红色 | 执行失败（Claude 出错 / 超时 / 代码提交失败等） |
| CANCELLED | 灰色 | 被用户手动取消 |

---

## 7. 配置项参考

以下环境变量在部署时配置（`deploy/.env` 或 Docker Compose 环境变量）：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `GITLAB_URL` | GitLab 实例地址 | `https://gitlab.example.com` |
| `GITLAB_BOT_TOKEN` | Bot 账号 PAT（`api` 权限） | `glpat-xxxx` |
| `GITLAB_WEBHOOK_SECRET` | 全局 Webhook 验签密钥 | 随机字符串 |
| `ANTHROPIC_BASE_URL` | Claude API 端点 | `https://api.anthropic.com` |
| `ANTHROPIC_API_KEY` | Claude API 密钥 | `sk-ant-xxxx` |
| `ANTHROPIC_MODEL` | 使用的模型 | `claude-opus-4-5` |
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://...` |
| `DOCKER_HOST` | Docker 引擎地址 | `tcp://localhost:2376` |
| `WORKER_IMAGE` | Worker 容器镜像 | `gitlab-issues-to-mr-worker:latest` |
| `MAX_CONCURRENCY` | 最大并发 Worker 数 | `3` |
| `TASK_TIMEOUT` | 任务超时秒数 | `1800` |
| `DEFAULT_TARGET_BRANCH` | 默认 MR 目标分支 | `main` |
| `CONFIG_ENCRYPTION_KEY` | 配置加密密钥 | 32 字节 base64 |
| `AUTO_MIGRATE` | 启动时是否自动执行数据库迁移 | `true` / `false` |

> 运行时配置（并发数、超时、Claude Max Turns 等）也可以通过 Dashboard 配置页面动态修改，无需重启服务。

---

## 8. 常见问题

**Q: 评论了 `@ai-bot` 但没有任何反应？**

1. 检查 Webhook 是否已配置并触发（GitLab → 项目 → Settings → Webhooks → 查看最近的请求）
2. 检查 Bot 账号是否有项目的 Developer 权限
3. 检查 Webhook Secret 是否与服务端配置一致
4. 查看 backend 服务日志：`docker logs gimr-backend --tail 50`

---

**Q: 任务显示 FAILED，如何排查？**

1. 打开任务详情页，查看**日志面板**的完整输出（支持颜色，ANSI 格式）
2. 关注 `❌ Error` 行和最后的 `Exit code` 信息
3. 常见原因：
   - Claude API 超额或网络不通
   - 代码语法错误导致测试失败
   - 仓库权限不足（无法推送分支）
   - 任务超时（默认 30 分钟，可在配置页调整）

---

**Q: 如何调整 Claude 的工作深度（Max Turns）？**

进入 **Configuration → 运行时配置**，修改 **Claude Max Turns** 字段（范围 1–1000）。

- 增大 Max Turns：Claude 可以执行更多工具调用，适合复杂任务
- 减小 Max Turns：更快返回结果，适合简单任务，节省 token

---

**Q: 如何查看 token 消耗？**

在任务详情页的**基础信息**面板中，"Token 用量"行显示本次调用的输入/输出 token 数。

- **输入（Input）**：包含系统提示、上下文、工具定义
- **输出（Output）**：Claude 生成的文本和工具调用

历史任务（在 token 统计功能上线前创建的任务）不显示此字段（显示 `-`）。

---

**Q: 多个任务同时触发会怎样？**

调度器维护一个**并发上限**（默认 3，可配置）。超过上限的任务进入队列等待。

此外，系统对**同一个 Issue 的并发任务**有互斥保护：同一 Issue 下不会同时运行两个任务，后来的任务会等待前一个完成后再执行。

---

**Q: Worker 容器命名规则是什么？**

每个 Worker 容器的命名格式为：

```
gimr-{task_id}-p{project_id}-i{issue_iid}
```

例如：`gimr-42-p7-i15`，表示任务 #42，项目 ID 7，Issue #15。

手动任务（无 Issue）中 `issue_iid` 部分为 `iNone`。

---

**Q: 日志中的颜色和 emoji 不显示？**

请确认使用的是最新部署版本。GIMR 支持 ANSI 颜色渲染和 emoji 显示，旧版本日志以纯文本格式存储，升级后的新任务日志将正常显示颜色和 emoji。

---

## 相关文档

- [DEPLOYMENT.md](DEPLOYMENT.md) — 详细部署指南
- [GITLAB_WEBHOOK_SETUP.md](GITLAB_WEBHOOK_SETUP.md) — Webhook 配置步骤
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md) — GitLab OIDC 登录配置
- [e2e-debugging.md](e2e-debugging.md) — 端到端调试指南
- [DESIGN.md](DESIGN.md) — 系统架构设计文档
