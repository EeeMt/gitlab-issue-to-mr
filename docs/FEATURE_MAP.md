# Codify 项目功能地图

> 系统性地梳理当前项目所有功能，粒度到具体操作/交互层面。

![Codify 功能地图](FEATURE_MAP.svg)


---

## 1. 任务执行与生命周期

### 1.1 任务创建
- 手动创建任务（从 Issue 页发起）
- 创建任务时选择 AI Provider
- 创建 Issue 时显式选择 Worker Profile；Issue 内任务固定继承且不能切换
- 创建任务时填写 user prompt（自由文本）
- 创建任务时引用 Prompt Template（模板库选择、标签筛选、覆盖确认）
- 创建任务时编辑 Run Instruction Template（变量占位符提示、预览渲染）
- 创建任务时设置优先级（P0/P1/P2）
- 创建任务时设置执行模式（execute 需代码变更 / plan 仅分析方案）
- 创建任务时选择调度方式：立即执行 / 延时执行（相对秒数）/ 定时执行（绝对时间）
- 定时执行时选择时间（热力图选时段、slot 容量检查、槽满提示）
- 任务创建时的用量限额校验（超限阻断）
- 任务创建时自动渲染 prompt 模板
- 任务创建时自动快照 Worker Profile 配置
- CI 自动修复自动创建任务（Webhook → Pipeline 失败 → 收集证据 → 创建修复任务）
- 重试任务（从失败/取消的任务克隆新任务，保留关联）
- 编辑未开始的任务（PATCH 修改 prompt、优先级、调度时间、Provider 等字段）
- 重新调度未开始的任务（RescheduleDrawer 修改定时执行时间）

### 1.2 任务调度
- 优先级队列（P0 > P1 > P2；同优先级定时任务优先于立即任务；同类型按 scheduled_at 再按 created_at 排序）
- 并发控制（max_concurrency 限制同时运行任务数）
- Issue 执行锁（同一 Issue 同时只运行一个任务）
- 定时任务到时自动标记 QUEUED
- 用量限制检查（调度时拒绝超限用户的任务）
- 崩溃恢复（调度器重启时发现 running 容器并恢复监控；已退出容器仍可收集日志/结果）
- 孤儿容器清理（调度器重启时清理无对应任务的容器）
- 卡住任务标记失败（调度器重启时标记无容器/已退出容器的 RUNNING 任务）
- 调度器独立进程运行（scheduler_service.py 作为独立进程，与 Web Server 分离）
- 线程池隔离（每个任务在独立线程+event loop 中执行）

### 1.3 任务执行
- Docker 容器隔离运行（`codify-{task_id}-p{project_id}-i{issue_iid}`）
- 容器环境变量注入（GitLab token、AI provider 配置、自定义 env vars）
- Worker Profile 环境变量注入（profile 级别的自定义变量 + 加密标记）
- 全局 Worker 环境变量注入（全局级别自定义变量，通过 Runtime Config 管理，保留字校验）
- 容器 Volume 挂载（workspace、CA 证书、自定义挂载、Claude session 存储目录）
- Pre-script 执行（容器内前置脚本）
- Post-script 执行（容器内后置脚本）
- Codegraph 支持（profile 级别开关）
- Claude CLI 调用执行代码生成
- SSH 客户端内置（worker 镜像内）
- 容器日志实时采集（结构化 event.jsonl + console.log）
- 日志敏感数据脱敏（glpat-* token、sk-ant-* key、ANSI 转义码）
- 超时控制（task_timeout 秒后强制终止）
- 手动取消运行中的任务
- Workspace 状态查询（查看 Issue 工作空间目录是否存在、路径信息）
- Workspace 删除（手动清理持久化的工作空间）

### 1.4 任务结果
- MR 自动创建/更新到 GitLab
- 代码变更统计（additions / deletions / total_changes）
- Token 用量统计（input_tokens / output_tokens）
- Commit SHA 记录
- MR URL 关联到 Issue
- MR 统计查询与持久化（代码增删行数，可从 GitLab 回退查询）
- AI 生成的 commit message
- 使用的 AI 模型名称记录
- 执行时长记录（started_at → completed_at）
- 任务状态机：PENDING → QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED
- require_changes 失败逻辑（execute 模式下无代码变更→标记失败）
- 手动覆盖任务状态（is_manually_overridden，记录操作人、原因、时间）
- Claude 会话续接（RESUME_SESSION 环境变量 + Volume 持久化，后续任务可继承上一任务的对话上下文）
- 运行指标展示（模型名称、Token 用量、执行时长、技能调用次数、上下文压缩次数）

---

## 2. Issue 管理

### 2.1 Issue CRUD
- 创建 Issue（项目、标题、描述、分支配置）
- 编辑 Issue（标题、描述、状态）
- 关闭 Issue（自动删除 GitLab 分支可配、记录关闭方式）
- 删除 Issue（有活跃任务时返回 409 阻止删除）
- Issue 列表（分页、筛选、排序）
- Issue 详情（含关联任务列表）

### 2.2 Issue 分支管理
- 创建时指定 base branch + target branch
- 自动生成 branch name（格式 `codify/issue-{id}`，不可自定义）
- 关闭时自动删除分支（delete_branch_on_close 开关）
- 手动删除分支（已关闭 Issue）
- 分支删除状态追踪（branch_deleted 标记）

### 2.3 Issue 运行配置
- 默认 AI Provider（Issue 级别，新建任务时继承）
- 固定 Worker Profile（Issue 创建后不可切换，普通任务/重试/CI 修复统一继承）
- CI 自动修复开关（ci_auto_repair_enabled）

### 2.4 Issue 状态
- 状态机：OPEN → IN_PROGRESS → IN_REVIEW → CLOSED
- 自动转换：创建首个任务时 → IN_PROGRESS
- 自动转换：任务完成/失败后可能更新状态

---

## 3. 日志与可观测性

### 3.1 结构化日志（TaskLog）
- 日志类型区分：thinking / assistant_text / tool_call / context_compact / system_init
- 日志级别标记（log_level）
- 日志元数据存储（log_metadata JSON）
- 时间线视图渲染（TaskProcessPanel 事件时间线）
- 工具调用展开（查看 input/output 完整内容）
- Payload 懒加载（大体积 tool call 内容存储到 TaskPayload 表，按需查询）

### 3.2 原始日志（Raw Log）
- Console 日志分块存储（TaskRawLogChunk，按 sequence_no 排序，支持 identity 编码）
- 原始日志 SSE 流式推送（/raw-log-stream）
- 容器日志直接流式传输（/container-logs 轮询）
- 任务完成后日志 finalized 标记
- 原始日志面板（TaskProcessRawPane 终端风格展示）

### 3.3 日志流式传输（SSE）
- 结构化日志 SSE 流（/log-stream，批量推送）
- 原始日志 SSE 流（从已持久化 chunk 推送）
- 自动重连机制（useTaskLogStreams composable）
- Tab 切换时生命周期管理

### 3.4 运行归档（TaskRunArchive）
- 任务完成后打包归档（event.jsonl + runtime.json + console.log）
- 归档元数据查询
- 归档文件下载

---

## 4. AI 交付物展示

### 4.1 交付摘要（Delivery Summary）
- Markdown 渲染摘要内容
- 懒加载摘要文本（从 TaskPayload 按 payload_id 查询）
- 摘要源文本复制（保留原始 Markdown 格式）

### 4.2 Mermaid 图表
- 自动检测 ```mermaid 代码块
- SVG 渲染（mermaid 库）
- 缩放弹窗查看器（fit / 100% / 150% / 200% / 300%）
- 鼠标拖拽平移
- 滚轮缩放
- Mermaid 源码复制

### 4.3 交互辅助
- 摘要折叠浮动按钮（滚动时自动显现）
- 复制反馈计时器

### 4.4 后续任务（TaskContinuationPanel）
- 任务完成后引导创建后续任务（追加同一 Issue 的新任务）
- 返回 Issue 详情的快捷入口

---

## 5. 统计分析

### 5.1 Dashboard 统计
- 任务状态统计卡片（各状态计数）
- 24 小时窗口趋势（新增/完成/失败任务数）
- Issue 状态统计
- 活动热力图（GitHub 风格天级热力图）
- 近期 Issue 列表
- 趋势折线图（ECharts：任务数、代码变更、Token 消耗）
- 状态饼图（Issue 状态分布 / 任务状态分布）
- "我的工作台"看板（MyWorkBoard：Running / Ready / Waiting 三列）

### 5.2 Analytics 分析页
- 时间窗口选择（7 / 30 / 90 天）
- 项目和发起人筛选
- 汇总统计卡片
- 趋势图（任务数、代码行数、Token 数）
- 按项目统计表
- 按发起人统计表
- Provider 对比图表
- P0/P1/P2 队列等待时间分布
- 失败原因分类统计

### 5.3 调度统计
- 调度任务聚合统计（scheduled stats）
- 活动定时任务列表
- 时段热力图（7天 x 24小时）
- 忙碌/空闲时段识别
- 时隙容量可视化
- 管理员内联编辑任务时隙（在调度面板直接修改定时任务时间）

---

## 6. 系统监控

### 6.1 运行时概览
- 队列压力指示（pending/queued 任务数）
- Worker 对齐状态（运行容器数 vs 配置并发数）
- 失败率监控
- 长时间运行任务检测

### 6.2 容器调试
- 运行中 Worker 容器列表（容器 ID、名称、状态、创建时间）
- 容器日志实时 SSE 流
- Docker 健康检查

### 6.3 活跃任务管理
- 看板视图（Kanban 按状态分列）
- 时间线视图
- 表格视图（完整任务列表+筛选排序）

---

## 7. 配置管理

### 7.1 运行时配置（Runtime Settings）

通过 API 可读写（持久化到 system_config 表）：
- 调度器并发数（max_concurrency）
- 调度间隔（scheduler_interval）
- 任务超时时间（task_timeout）
- 默认目标分支（default_target_branch）
- 最大重试次数 / 重试延迟（max_retries / retry_delay）
- Slot 容量限制（slot_max_tasks / slot_max_tasks_enforce）
- CI 自动修复最大尝试次数（ci_auto_repair_max_attempts）
- AI Provider 全局默认（base_url / api_key / model / max_turns）
- Worker Volume 挂载配置
- Worker Pre/Post Script
- Worker CA 证书路径
- Worker Workspace 路径及保留天数（成功/失败任务分开配置）
- 全局 Worker 环境变量（非 Profile 级别，注入所有容器；加密标记；保留字校验）
- 功能开关（允许用户访问 Monitor / ScheduleOverview / Analytics / OIDC Diagnostics）
- 系统公告（启用/文本/级别）
- 配置加密存储（6 个敏感 key 使用 Fernet 加密落库，由 config_encryption_key 派生）
- 单 key 配置重置（DELETE /api/config/runtime/{key} 恢复为环境变量默认值）
- 全量配置重置（POST /api/config/reset 恢复所有配置为环境变量默认值）

仅通过环境变量配置（不可运行时修改）：
- Docker 守护进程地址（docker_host）、TLS 证书（docker_tls_ca/cert/key）
- SSL/TLS 自定义 CA Bundle（custom_ca_bundle）
- Worker 默认镜像（worker_image）、网络（worker_network）、容器名前缀（worker_container_prefix）
- Worker 跳过镜像拉取（worker_skip_image_pull）
- 数据库连接（database_url）
- 加密主密钥（config_encryption_key、secret_key、session_secret）
- 自动迁移开关（auto_migrate）
- 日志级别（log_level）、SQL echo（sqlalchemy_echo）
- 后端/前端 URL（backend_url、frontend_url）

### 7.2 GitLab 集成配置
- GitLab URL / Bot Token / Admin Token
- 连接测试（验证 token 有效性）
- 项目缓存失效刷新
- 项目级 Webhook 管理（创建/更新/查看状态）
- 全局 Webhook 状态总览

### 7.3 OIDC 认证配置
- GitLab OIDC issuer / client_id / client_secret / redirect_uri
- 连接测试
- OIDC 诊断（issuer 发现、endpoint 元数据、scope 需求、cookie 策略）
- Admin 用户名/组配置

### 7.4 Session 与安全
- Session Cookie 名称
- Session TTL（秒）
- Session 保留天数
- Cookie Secure / SameSite 策略

### 7.5 告警配置
- 告警 Webhook URL
- 失败告警开关（alert_on_failure）

### 7.6 Run Instruction Template 内置模板
- 系统内置不变模板元数据查询（/api/config/run-instruction-template-built-ins）
- 创建任务时查询有效默认模板（/api/tasks/run-instruction-template-defaults）

---

## 8. Mattermost 通知

### 8.1 集成配置
- Mattermost Server URL + Bot Token 配置
- 连接测试（验证 bot 身份）
- Channel 目标解析（team name + channel name → channel_id，支持反向查询）

### 8.2 通知 Profile 管理
- 创建/编辑/删除通知 Profile
- Profile 命名
- 目标类型：Channel / DM（发起人私信）
- 频道内 @mention 开关
- 订阅事件类型选择（多选）：
  - task_completed（任务完成）
  - task_failed（任务失败）
  - task_rescheduled（任务改期）
  - task_execute_now（改为立即执行）
  - task_retry_scheduled（重试已安排）
  - task_cancelled（任务已取消）
- 展示字段选择（多选）：任务 ID、项目、Issue、MR、发起人、状态、分支、目标分支、预约时间、时间变更、错误摘要、任务链接

### 8.3 用户映射
- GitLab username → Mattermost user 自动匹配
- 映射缓存（MattermostUserMapping 表）
- 上次验证时间追踪

### 8.4 投递追踪
- 每次通知的投递状态记录（success / failed / skipped）
- 投递目标摘要
- 失败原因记录

---

## 9. CI 失败自动修复

### 9.1 Webhook 接收
- GitLab Webhook 事件接收（通过 X-Gitlab-Token 验证）
- Pipeline 失败事件识别
- MR 关联事件处理

### 9.2 证据收集
- 失败 Pipeline 信息记录（pipeline_id / sha / ref / status / url）
- 失败 Job 列表采集（job_id / name / stage / status / failure_reason）
- Job 日志 Trace 下载
- 根因分析策略（first_failed_stage）
- 下游 Job 抑制标记（已失败的 stage 之后的 Job）
- 收集锁机制（防止并发收集同一个 failure run）
- 收集重试（collection_attempts 追踪）
- 已忽略原因记录（如非 MR pipeline）

### 9.3 Issue 关联
- 通过 source_branch + target_branch + project 匹配已有 Issue
- 无匹配 Issue 时自动创建

### 9.4 修复任务
- 自动创建修复任务（关联 CI failure run）
- 使用 CI Auto Repair Run Instruction Template
- 收集过程日志记录（CIFailureRunLog：step / status / message / details）
- CI Failure Collector 作为持久后台进程运行（与 Scheduler 共同启动）

### 9.5 CI 相关查询
- 按 Issue 查看 CI Failure Run 列表
- CI Failure Run 详情（含 Job 列表）
- CI Failure Run 日志时间线
- 按 Issue 查看 Webhook 事件列表

---

## 10. 提示词模板（Prompt Templates）

- 模板 CRUD（名称、内容、变量提示 variable_tips）
- 模板标签分类（tags，最多 20 个，每个最长 30 字符）
- 模板启用/禁用（is_active）
- 模板排序（拖拽排序持久化 sort_order）
- 模板列表按 sort_order → created_at → id 排序
- 前端模板选择器（标签筛选、应用模板到编辑器、覆盖确认）

---

## 11. AI Provider 管理

- Provider CRUD（名称、base_url、api_key、model、max_turns、system_prompt）
- 设为默认 Provider（is_default，单例唯一约束）
- 启用/禁用 Provider（is_disabled）
- 删除 Provider
- Provider 列表查询
- 创建 Issue 和创建 Task 时选择 Provider

---

## 12. Worker Profile 管理

- Profile CRUD（名称、描述、镜像、启用/禁用）
- 设为默认 Profile（is_default，单例唯一约束）
- Codegraph 开关
- Volume 挂载配置（JSON 数组）
- Pre/Post Script 配置
- Profile 级环境变量管理（key/value/加密标记）
- 三种 Run Instruction Template（default_execute / default_plan / ci_auto_repair）
- 复制 Profile（加密变量保留）
- 禁用 Profile
- Task 执行时 Profile 配置快照（TaskWorkerProfileSnapshot 不可变记录）

---

## 13. 用量管理（Usage Limits）

### 13.1 配额模型
- 日 Token 限额（daily_tokens）
- 周 Token 限额（weekly_tokens）
- 日任务数限额（daily_tasks）
- 周任务数限额（weekly_tasks）
- 三种配额模式：custom（自定义）/ inherit（继承系统默认）/ unlimited（无限制）

### 13.2 配额策略
- 系统默认策略（scope_type = system_default，单例）
- 用户级覆盖策略（按 user_id 唯一）
- 用量账本（TaskUsageLedger：按 task_id 唯一，记录 token 消耗和按天/周时间桶）

### 13.3 配额检查
- 创建任务时检查用户限额
- 调度执行前检查限额
- 超限时返回详细错误（含限额值和重置时间）
- 前端展示剩余用量和当前用量

### 13.4 管理界面
- 用户用量列表（管理员查看所有用户限额）
- 编辑系统默认限额
- 编辑单用户限额

---

## 14. 用户与权限

### 14.1 认证方式
- GitLab OIDC 登录（/api/auth/login 跳转 → callback）
- 本地用户名/密码登录（local auth）
- Break-glass 应急登录（预配置的紧急管理员账号）
- 登出（清除 Session Cookie）
- 认证审计日志（AuthAuditLog：事件类型、用户名、成功/失败、IP、User-Agent）

### 14.2 会话管理
- Session Cookie 机制
- Session 列表查看（当前用户自己的会话）
- 单 Session 撤销
- 管理员批量撤销某用户所有 Session
- Session 自动过期+清理（session_retention_days）
- Session 元数据记录（IP、User-Agent、last_seen_at）
- GitLab OIDC Token 加密存储于 Session（access_token + refresh_token，供 Worker 容器使用）

### 14.3 用户角色
- 平台角色：platform_admin / platform_user
- 角色来源追踪（bootstrap / manual / oidc）
- 用户状态：active / disabled
- 管理员编辑用户角色和状态
- OIDC 自动映射管理员（根据 auth_admin_usernames / auth_admin_gitlab_groups）

### 14.4 页面权限
- 4 个受控页面：Monitor / ScheduleOverview / Analytics / OIDC Diagnostics
- 功能开关控制（allow_*_for_users 配置项）
- OIDC 禁用时所有页面无限制
- Admin 用户始终全权限

### 14.5 系统初始化
- Bootstrap 流程（首次启动创建初始管理员）
- Bootstrap 状态追踪（SystemBootstrap 单行表）
- 初始化前阻止所有操作

---

## 15. GitLab 集成

### 15.1 项目管理
- 获取可访问的 GitLab 项目列表
- 查询项目分支列表
- 检查项目 CI 自动修复可用性（验证 Webhook 配置是否就绪）

### 15.2 Webhook 管理
- 单项目 Webhook 创建/更新（自动配置 pipeline events）
- 单项目 Webhook 状态查看
- 全局 Webhook 状态总览（所有可管理项目）
- Webhook Secret 加密存储

### 15.3 Webhook 事件
- 事件日志记录（WebhookEvent 表）
- 按项目+时间查询事件
- 按 Issue 查询关联事件
- 事件结果追踪（processed / unmatched / ignored）

### 15.4 MR 操作
- Worker 容器内自动创建/更新 MR
- MR URL 关联到 Issue
- MR 描述更新
- MR Draft 状态管理

---

## 16. 系统运维

### 16.1 数据清理
- 旧 Session 清理（保留期内未活动的会话）
- 过期 Workspace 清理（worker_workspace_retention_days）
- 旧归档清理
- 旧容器清理
- 手动触发全量数据清理（Maintenance Panel）

### 16.2 自动迁移
- 调度器启动时自动执行数据库迁移（Alembic auto-migrate）
- 调度器启动时回填活跃任务的 rendered_prompt

### 16.3 健康检查
- /health 端点（DB 连接 + Docker 连接检测，返回 status、checks、trace_id）
- 事件循环延迟监控（>1s 告警）

### 16.4 请求追踪
- 每个请求分配 X-Trace-ID（请求头传入或自动生成 UUID）
- Trace ID 返回响应头
- 慢请求告警（>2s 记录警告日志）

### 16.5 请求日志
- 请求开始/结束/耗时日志
- 错误全局异常处理（500 + Trace ID + 错误详情）

---

## 17. 前端基础设施

### 17.1 国际化（i18n）
- 中英文双语（en / zh-CN）
- 自动检测浏览器语言偏好
- localStorage 持久化语言选择
- Naive UI 组件库 locale 联动
- 日期格式化 locale 联动

### 17.2 UI 组件库
- Naive UI 全局配置（主题色自定义、locale）
- Message / LoadingBar / Dialog 全局 Provider
- 响应式断点（isMobile < 768px / isCompact < 480px）

### 17.3 通用组件
- App.vue 内全局布局（侧边栏导航 + 顶栏 + 系统公告横幅 + 内容区）
- PageHeader（标题+副标题+操作区）
- SummaryCard（统计卡片）
- StatCard（通用数据卡片）
- FilterToolbar（搜索+筛选+排序+列显隐）
- FilterPopover（分类筛选构造器）
- SortPopover（排序字段+方向选择）
- ColumnsPopover（列显隐开关）
- ErrorToast（全局错误弹窗）
- TraceBadge（Trace ID 调试标识）
- LanguageToggle（语言切换）
- PoweredByFooter（页脚）
- OnboardingModal（5 步产品引导）

### 17.4 API 层
- Axios 实例（/api 前缀、30s 超时、withCredentials）
- 401 自动跳转登录页（携带 next 参数和原因）
- Trace ID 请求/响应拦截器
- API 错误对象标准化

### 17.5 通用 Composables
- useFilterSort（筛选排序状态+localStorage 持久化）
- usePolling（定时轮询+Tab 可见性感知）
- useBreakpoints（响应式断点）
- useOnboarding（引导弹窗关闭状态持久化）
- useVariableEditor（CodeMirror 编辑器+变量提取）
- useConfigForm（Config 页面多标签页表单状态管理，脏检测、跨面板保存）

### 17.6 任务 Feature Composables（frontend/src/features/tasks/）
- taskFormModel（TaskFormDraft 类型、buildCreateTaskRequest / buildUpdateTaskRequest 请求构建）
- useTaskFormSubmission（创建/编辑任务表单提交、校验、用量检测、槽满错误处理）
- useTaskExecutionOptions（加载 AI Provider 和 Worker Profile 列表、计算默认选项）
- useTaskSlotCapacity（带防抖的时隙容量检查）
- useTaskScheduleContext（加载定时任务和容量配置）
- useTaskLogStreams（结构化+原始日志 SSE 流，自动重连，Tab 生命周期管理）
- useDeliverySummaryPayload（按 payload ID 懒加载交付摘要文本）
- usePromptTemplatePicker（模板选择器：标签筛选、应用到编辑器、覆盖确认）
- useRunInstructionPreview（服务端预览渲染 run instruction 模板）
- useSummaryRenderer（Markdown 解析、Mermaid 代码块检测、SVG 渲染）
- useSummaryMermaidViewer（Mermaid 图表缩放弹窗：拖拽平移、滚轮缩放）
- useSummaryCollapseFloat（交付摘要折叠浮动按钮）
- useSummaryCopyActions（摘要源码和 Mermaid 源码复制到剪贴板）

### 17.7 工具函数
- datetime 格式化（UTC+8、紧凑格式、相对时间）
- priority/formatDuration/formatLargeNumber 格式化
- MR URL 提取
- Prompt Template 标签筛选

---

## 附录：数据模型关系速览

```
User ──→ UserSession (1:N)
User ──→ UsageLimitPolicy (1:1)
User ──→ Task (发起人 N:1)
User ──→ Issue (发起人 N:1)

Issue ──→ Task (1:N, cascade delete)
Issue ──→ IssueExecutionLock (1:1)
Issue ──→ WebhookEvent (1:N)
Issue ──→ CIFailureRun (1:N)
Issue ──→ AIProvider (default_provider, N:1)
Issue ──→ WorkerProfile (pinned worker, N:1, creation-time required)

Task ──→ TaskLog (1:N)
Task ──→ TaskRawLogChunk (1:N)
Task ──→ TaskPayload (1:N)
Task ──→ TaskRunArchive (1:1)
Task ──→ TaskIngestCursor (1:N)
Task ──→ TaskUsageLedger (1:1)
Task ──→ TaskWorkerProfileSnapshot (1:1)
Task ──→ AIProvider (N:1)
Task ──→ WorkerProfile (N:1)
Task ──→ CIFailureRun (source, N:1)
Task ──→ Task (retry_source → retry 链)

WorkerProfile ──→ WorkerProfileEnvironmentVariable (1:N)
WorkerProfile ──→ TaskWorkerProfileSnapshot (1:N)
WorkerProfile ──→ Task (1:N)
WorkerProfile ──→ Issue (default for, 1:N)

CIFailureRun ──→ CIFailureJob (1:N)
CIFailureRun ──→ CIFailureRunLog (1:N)
CIFailureRun ──→ Task (repair_task, 1:1)
CIFailureRun ──→ Task (repair_tasks, 1:N)

MattermostNotificationProfile ──→ MattermostNotificationDelivery (1:N)
MattermostUserMapping (独立映射表，user_id / gitlab_user_id / gitlab_username → mattermost_user_id)

ProjectWebhookConfig (按 project_id 唯一)
SystemConfig (按 key 唯一)
PromptTemplate (按 sort_order 排序)
WorkerEnvironmentVariable (按 key 唯一，全局注入所有 Worker)
WebhookEvent ──→ Issue (N:1)
```
