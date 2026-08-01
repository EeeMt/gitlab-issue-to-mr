# Phase 3：Claude + Codex 多 Host 灰度与生产验收实施计划

> 上级计划：[Codify 多 Harness 引擎分阶段实施总计划](2026-08-01-multi-harness-engine-roadmap.md)
> 前置产物：[Phase 2 Codex 与公共产品能力接入](2026-08-01-multi-harness-phase-2-codex-integration.md)

**目标：** 将冻结的 Claude + Codex release candidate 安装到所有目标 Docker Host，通过逐 Host 验证、小流量灰度、指标观察和回滚演练，形成可运营的双引擎生产基线。

**周期：** 2–4 人日。

**行为边界：** 本阶段不增加新协议能力、不升级 CLI、不修改 Adapter 映射；发现缺陷时停止扩量，回到 Phase 2 修复并重新生成完整制品。

---

## 1. 交付文件规划

- Create: `docs/runbooks/multi-harness-rollout.md` — Host 清单、安装、验证、灰度、告警和回滚步骤。
- Create: `docs/runbooks/multi-harness-rollout-evidence.md` — 可复制的逐 Host/逐 Harness 证据模板。
- Modify: `docs/worker-kits.md` — 双引擎固定版本、安装和 verify-runtime 示例。
- Modify: `deploy/offline-bundle/README.md` — 离线双引擎制品和 Host 路径说明。
- Modify as needed: `deploy/offline-bundle/config/worker-images.txt.example` — 必需 runtime image 示例。

运行产生的 Host 名称、内部地址、token、私有仓库 URL 和敏感日志不得提交到 Git；Git 中只保留脱敏模板，真实证据保存在受控发布系统。

---

## 2. 发布冻结清单

在安装任何 Host 前，记录并冻结：

- [ ] Backend image digest、Frontend/Nginx image digest 和数据库 migration head。
- [ ] Worker Kit 版本、两个架构的 archive SHA-256 和 manifest SHA-256。
- [ ] 每个 runtime image 的 repo digest，不使用可变 tag 作为验收依据。
- [ ] Claude/Codex CLI 版本、来源和 binary digest；Runtime Bundle manifest 中实际 Adapter version/digest；Kit compatibility manifest digest。
- [ ] Canonical Event schema、runtime contract、orchestration version 和 golden fixture commit。
- [ ] Profile payload、system upper bounds、sandbox/approval、network 和 credential delivery mode。
- [ ] 旧稳定 Backend/Frontend/Kit/Profile 的回滚坐标。

冻结后任何一项改变都必须产生新的 release candidate 和证据批次。

---

## 3. 任务拆分

### Task 3.1：建立 Host、架构与 Profile 部署矩阵

**Files:** `docs/runbooks/multi-harness-rollout.md`、evidence template。

- [ ] 列出所有可被 Worker Profile 选中的 Docker daemon，记录逻辑名称、CPU 架构、Docker 版本、连接方式、Kit 安装根、runtime images、私有 CA 和网络出口类别。
- [ ] 通过实际 Docker context/daemon 检查确认路径和镜像属于远程 Host，不把 Backend 本机路径当成 daemon host 路径。
- [ ] 为每个 Host 指定旧稳定 Profile、双引擎 canary Profile、目标 Profile、可进入 canary 的新 Issue cohort 和回滚负责人。
- [ ] 标记需要 amd64/arm64 Kit 和 CLI binary 的 Host，禁止跨架构复用制品。
- [ ] 记录 Provider 可达性；如果某 Host 不能访问某 Endpoint，不把它加入对应 Profile 路由。

**门禁：** 每个目标 Profile 都能唯一映射到 daemon、Kit path、image digest、Harness binary 和凭据策略。

### Task 3.2：导出并校验固定 Worker Kit 与离线包

**Files:** Worker Kit/offline docs 和制品证据。

- [ ] 使用 release candidate 的明确 Kit 版本导出所需架构制品。
- [ ] 将全部 runtime image 写入 offline worker image 清单并导出；检查加载后的 repo digest 与冻结值一致。
- [ ] 校验 Kit archive、checksum、compatibility manifest、Runtime Bundle Adapter 文件/digest、golden fixture smoke 和离线包内容。
- [ ] 在隔离临时目录做一次全新安装演练，验证安装器拒绝覆盖已有版本目录。
- [ ] 保留旧 Kit 安装目录和旧 runtime image，不做原地替换或删除。

示例命令中的版本必须替换为本次冻结值：

```bash
make worker-kit-export WORKER_KIT_VERSION=<release-version> WORKER_KIT_PLATFORM=linux/amd64
make worker-kit-export WORKER_KIT_VERSION=<release-version> WORKER_KIT_PLATFORM=linux/arm64
```

```bash
make offline-bundle-export WORKER_KIT_VERSION=<release-version>
```

### Task 3.3：逐 Host 安装并运行 runtime verification

**Files:** rollout evidence（真实证据不提交 Git）。

- [ ] 在每个 daemon host 使用 archive checksum 安装到新的版本路径，禁止覆盖旧目录。
- [ ] 加载所需 runtime images 并用 digest 检查实际内容。
- [ ] 对每个 Profile/Harness 组合运行离线 verify-runtime，检查 Kit compatibility manifest、Runtime Bundle Adapter version/digest、CLI source/path/version/binary digest、CA、PATH、工作区写权限、UID/GID、sandbox、Skills、Mermaid 和项目 toolchain smoke。
- [ ] 通过 `/api/worker-profiles/{id}/verify-runtime` 再运行一次 Codify 路径验证，确认 API 使用的是 Profile 固定 daemon。
- [ ] 对 remote Docker 特别验证 Host bind path、agent-state、Kit/Nix store 和 runtime bundle 均能在 daemon 侧访问。
- [ ] 任一 Host/ Harness 验证失败时标记为不可路由，不能依靠其他 Host 成功结果放行。

建议 evidence 至少记录：Host、时间、Kit compatibility manifest digest、Runtime Bundle/Adapter digest、image digest、CLI source/path/version/binary digest、verify task ID、exit code、脱敏日志摘要和审批人。

### Task 3.4：执行双引擎真实验收矩阵

**Files:** evidence template；必要时补充 `docs/runbooks/multi-harness-rollout.md`。

每个进入生产支持范围的 Harness 至少在一个目标 Host 完成，关键 Host 应全部覆盖：

- [ ] 新 Issue 首个 execute Task：分支、修改、提交、Push、创建/更新 MR。
- [ ] 成功但无文件变化；`require_changes` true/false 结果正确。
- [ ] 同一 Harness、同一 namespace 的后续 Task resume 成功。
- [ ] fresh session 明确不恢复旧 session。
- [ ] namespace 因 Endpoint/认证域/Adapter state 变化时显式新 lineage。
- [ ] Claude → Codex → Claude，Session 不串线且原 Claude lineage 可恢复。
- [ ] retry 继续使用原 Harness、Endpoint snapshot、image digest、Kit 和 Runtime Bundle。
- [ ] Task Skills 可发现且 `/workspace` Git diff 无 Skills 文件。
- [ ] 工具失败、Provider 认证失败、限流、网络中断和 protocol diagnostic 的失败分类正确。
- [ ] 取消、timeout、SIGTERM/KILL 能终止进程树并清理容器、Issue mutex 和工作区锁。
- [ ] Canonical Event、raw event、console、result、artifacts 可下载、清洗并离线回放。
- [ ] Git/MR、commit message fallback、delivery summary、Mermaid 和 Claude-only CodeGraph 行为正确。

每个用例记录 Task ID、Harness、attempt ID、Host、Profile snapshot、MR/commit、archive digest、结果和人工结论。

### Task 3.5：建立灰度指标、阈值和告警

**Files:** rollout runbook、监控配置（如本项目已有配置入口则在实施时列明实际文件）。

- [ ] 灰度前记录旧 Claude 基线：成功率、P50/P95 耗时、取消完成率、timeout、平均 token、protocol error 和 worker cleanup error。
- [ ] 新增按 Harness/Adapter/CLI/Profile/Host 的可筛选视图或查询，避免聚合掩盖单 Host 问题。
- [ ] 至少设置以下阻断阈值：任何错误成功判定、session 串线、凭据泄漏、无法取消、双 Task terminal、持续 seq 缺口。
- [ ] 为成功率、P95、rate limit、sandbox failure、protocol error、capability warning 和 runtime verification stale 设置阶段阈值。
- [ ] 样本不足时不按百分比自动放行；同时要求最小任务数和观察时间。
- [ ] 日志/归档告警内容必须先清洗，不能把 raw Provider 响应直接发送到外部通知。

### Task 3.6：按新 Issue cohort 执行 canary → 小流量 → 扩量

- [ ] 创建独立 canary Worker Profile，固定新 Kit、image digest 和双引擎 allowlist；不直接修改旧稳定 Profile。
- [ ] Canary 只分配给新创建的内部可信 Issue；现有 Issue 的 Worker Profile 不迁移，其后续 Task 继续使用原 Profile。
- [ ] 建议扩量阶梯为符合条件的“新建 Issue”5% → 25% → 50% → 100%，不是按 Task 动态路由。分配规则在 Issue 创建时一次确定，并记录 cohort/profile；每级必须满足预先记录的最小 Issue/Task 样本数、观察时间和阈值。
- [ ] 每一级复核错误分类、取消、归档、session、usage 和 Host 分布，不能只看总体成功率。
- [ ] 每个 Issue 内的新 Task 继续继承该 Issue 固定 Profile，并在创建时冻结 Task Snapshot；运行中和已创建 Task 均不做热切换。
- [ ] 任一阻断指标触发立即停止把新 Issue 分配到 canary Profile，并暂停 canary Issue 上的新 Task；保留运行证据并进入回滚。

### Task 3.7：演练回滚并完成生产签署

- [ ] 回滚把“新 Issue 的默认/分配规则”恢复到旧稳定 Profile/Kit；不能把既有 Issue 或 Task 路由改写到旧 Profile。
- [ ] 已进入 canary cohort 的 Issue 如必须继续工作，停止在原 Issue 创建 Task，按 runbook 创建关联的 replacement Issue 并在创建时选择旧稳定 Profile；保留原 Issue、Task、Session 和证据链，不复制跨 Profile/Harness session ID。
- [ ] 运行中和已创建 Task 的 Snapshot 不修改、不强制切 Harness；是否允许其自然完成或取消由阻断指标级别决定并记录。
- [ ] 验证旧 Backend/Frontend 与新增数据库字段的兼容窗口；数据库 downgrade 不是默认回滚手段。
- [ ] 演练新 Kit 验证失败、Codex Provider 不可达、单 Host 故障和 canonical protocol error 上升四种场景。
- [ ] 确认旧 Kit path、runtime image、Profile 和 Provider credential 仍可用。
- [ ] 回滚后新建一个使用旧稳定 Profile 的 Issue，再创建 Claude smoke Task，验证 Issue 分配与完整执行路径均已恢复。
- [ ] 汇总每个 Host/Harness 的安装、验证、smoke、灰度、指标和回滚证据，完成生产签署。

---

## 4. Phase 3 完成定义

- [ ] 所有目标 Host 的 Kit、image digest、CLI/Adapter、CA/PATH、sandbox、workspace 和 agent-state 验证通过。
- [ ] Claude/Codex 真实验收矩阵无 P0/P1 缺陷，阻断指标为零。
- [ ] 新 Issue cohort 灰度达到目标比例和最小 Issue/Task 样本，指标在批准阈值内。
- [ ] 新 Issue 分配已成功回滚到旧 Profile/Kit，replacement Issue 流程通过，且未修改既有 Issue Profile 或 Task Snapshot。
- [ ] 证据能区分源码测试、制品安装、真实 smoke 和灰度结果。
- [ ] 运维 runbook、Host 清单、告警和责任人已完成交接。

达到以上条件后，Claude + Codex 才可标记为生产基线。OpenCode 仍保持未启动，至少等待一个稳定 Worker Kit 发布周期后再评估 Phase 4 准入。
