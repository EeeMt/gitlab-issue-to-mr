# Phase 3：Claude + Codex 多 Host 直接切换与生产验收实施计划

> 上级计划：[Codify 多 Harness 引擎分阶段实施总计划](2026-08-01-multi-harness-engine-roadmap.md)
> 前置产物：[Phase 2 Codex 与公共产品能力接入](2026-08-01-multi-harness-phase-2-codex-integration.md)
> 修订（2026-08-05）：取消 canary/灰度发布，改为全部目标 Host 验证完成后直接切换；保留切换前基线、指标告警与回滚演练。

**目标：** 将冻结的 Claude + Codex release candidate 安装到所有目标 Docker Host，通过逐 Host 验证、一次性直接切换、指标观察和回滚演练，形成可运营的双引擎生产基线。

**周期：** 2–4 人日。

**行为边界：** 本阶段不增加新协议能力、不升级 CLI、不修改 Adapter 映射；发现缺陷时立即停止切换并回到 Phase 2 修复，重新生成完整制品。

---

## 1. 交付文件规划

- Create: `docs/runbooks/multi-harness-rollout.md` — Host 清单、安装、验证、切换、告警和回滚步骤。
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
- [ ] 为每个 Host 指定旧稳定 Profile、目标 Profile 和回滚负责人。
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

### Task 3.5：建立切换指标、阈值和告警

**Files:** rollout runbook、监控配置（如本项目已有配置入口则在实施时列明实际文件）。

- [ ] 切换前记录旧 Claude 基线：成功率、P50/P95 耗时、取消完成率、timeout、平均 token、protocol error 和 worker cleanup error。
- [ ] 新增按 Harness/Adapter/CLI/Profile/Host 的可筛选视图或查询，避免聚合掩盖单 Host 问题。
- [ ] 至少设置以下阻断阈值：任何错误成功判定、session 串线、凭据泄漏、无法取消、双 Task terminal、持续 seq 缺口。
- [ ] 为成功率、P95、rate limit、sandbox failure、protocol error、capability warning 和 runtime verification stale 设置切换后观察阈值。
- [ ] 切换后设置最小观察任务数和观察时间，样本不足时不认定切换成功。
- [ ] 日志/归档告警内容必须先清洗，不能把 raw Provider 响应直接发送到外部通知。

### Task 3.6：完成直接切换与稳定观察

- [ ] 切换前确认 3.1–3.5 全部完成：Host 矩阵、制品冻结与校验、逐 Host verify-runtime、真实验收矩阵和基线指标就绪。
- [ ] 执行发版硬边界操作：关闭/处理历史 Issue，drain 或取消 PENDING/QUEUED/RUNNING 旧任务，切换窗口内无旧 Kit/旧镜像任务在途。
- [ ] 一次性把所有启用 Worker Profile 切到冻结的 Kit、image digest、harness allowlist/约束和凭据策略；任一 Host 未通过 verify-runtime 不得恢复调度。
- [ ] 切换后立即创建 Claude + Codex smoke Task，验证完整 Git/MR、session、cancel/timeout 和归档回放链路。
- [ ] 每个 Issue 内的新 Task 继续继承该 Issue 固定 Profile，并在创建时冻结 Task Snapshot；运行中和已创建 Task 均不做热切换。
- [ ] 任一阻断阈值触发立即停止新 Task 创建，保留运行证据并按 3.7 回滚。

### Task 3.7：演练回滚并完成生产签署

- [ ] 回滚把所有启用 Profile 和新 Task 分配恢复到旧稳定 Profile/Kit；不能把既有 Issue 或 Task 路由改写到旧 Profile。
- [ ] 切换后已运行新 Kit 的 Issue 如必须继续工作，停止在原 Issue 创建 Task，按 runbook 创建关联的 replacement Issue 并在创建时选择旧稳定 Profile；保留原 Issue、Task、Session 和证据链，不复制跨 Profile/Harness session ID。
- [ ] 运行中和已创建 Task 的 Snapshot 不修改、不强制切 Harness；是否允许其自然完成或取消由阻断指标级别决定并记录。
- [ ] 验证旧 Backend/Frontend 与新增数据库字段的兼容窗口；数据库 downgrade 不是默认回滚手段。
- [ ] 演练新 Kit 验证失败、Codex Provider 不可达、单 Host 故障和 canonical protocol error 上升四种场景。
- [ ] 确认旧 Kit path、runtime image、Profile 和 Provider credential 仍可用。
- [ ] 回滚后新建一个使用旧稳定 Profile 的 Issue，再创建 Claude smoke Task，验证 Issue 分配与完整执行路径均已恢复。
- [ ] 汇总每个 Host/Harness 的安装、验证、smoke、切换、指标和回滚证据，完成生产签署。

---

## 4. Phase 3 完成定义

- [ ] 所有目标 Host 的 Kit、image digest、CLI/Adapter、CA/PATH、sandbox、workspace 和 agent-state 验证通过。
- [ ] Claude/Codex 真实验收矩阵无 P0/P1 缺陷，阻断指标为零。
- [ ] 直接切换完成：所有目标 Host 与启用 Profile 均已切换到冻结版本，切换后稳定观察期指标在批准阈值内。
- [ ] 切换已成功回滚到旧 Profile/Kit，replacement Issue 流程通过，且未修改既有 Issue Profile 或 Task Snapshot。
- [ ] 证据能区分源码测试、制品安装、真实 smoke 和切换结果。
- [ ] 运维 runbook、Host 清单、告警和责任人已完成交接。

达到以上条件后，Claude + Codex 才可标记为生产基线。OpenCode 仍保持未启动，至少等待一个稳定 Worker Kit 发布周期后再评估 Phase 4 准入。

---

## 5. 实施记录（2026-08-05，dev 目标 Host 演练）

本阶段 Git 交付物与 dev 目标 Host 演练已完成；真实生产 Host 的生产签署仍按 Runbook 执行。

### 已完成

- [x] `docs/runbooks/multi-harness-rollout.md`：发布冻结、Host 矩阵、安装/verify、直接切换、
      指标/阈值/告警、回滚与生产签署流程。
- [x] `docs/runbooks/multi-harness-rollout-evidence.md`：逐 Host / 逐 Harness / 验收矩阵 /
      切换 / 回滚 / 签署的脱敏证据模板。
- [x] `docs/worker-kits.md`：Kit `0.3.10` 双引擎安装与 verify-runtime 示例，镜像 digest 固定说明。
- [x] `deploy/offline-bundle/README.md` 与 `config/worker-images.txt.example`：release candidate
      freeze、必需 runtime image 与逐 Harness verify 说明。
- [x] Kit/export 默认版本升级到 `0.3.10`（`Makefile`、`deploy/Dockerfile.worker-kit`、
      `deploy/worker-kit/export.sh`）。
- [x] 发布冻结值：Kit `0.3.10` archive/manifest SHA-256、Claude `2.1.153`、
      Codex `0.146.0` binary digest、runtime image repo digest、Backend/Nginx registry digest、
      migration head `065_worker_profile_verification`、Runtime Bundle digest `00addfc6...`。
- [x] dev 目标 Host（x86_64，Docker `28.5.2`）：Kit `0.3.10` 已安装且 manifest 与本地制品一致；
      claude/codex 离线 verify-runtime 均通过；安装器拒绝覆盖已安装版本目录。
- [x] Codify API `/api/worker-profiles/11/verify-runtime` 通过，Profile 11 持久化
      `image_digest`/`verified_at`。
- [x] 直接切换：Profile 11 镜像引用固定为 `repo@sha256:a9d046b1...` 并设为系统默认；
      新 Issue 87 的 Task 538（codex）/539（claude）completed，commit + MR !6，
      canonical event 连续、唯一 `run.completed` 终态。
- [x] 回滚演练：Profile 11 恢复 tag 坐标并 re-verify，Task 540（claude）completed；
      随后重新切回 digest 坐标并复验；旧 Kit `0.3.9` 目录保留。
- [x] 发版硬边界（dev 目标 Host）：关闭全部切换前历史 Issue（57 个，保留分支），禁用旧
      Profile 1/12；当前仅 Profile 11 启用且为默认，无在途任务、无残留 worker 容器。
- [x] 切换后 cancel/timeout 证据：Task 541 cancel → canonical `run.failed(cancelled)`；
      Task 542 timeout=60 → canonical `run.failed(timeout)` + archive 回放连续（已恢复 1800）。
- [x] 完整回滚 + replacement Issue：恢复旧 tag 坐标，Issue 88 + Task 543（claude）
      completed（commit + MR !7），随后恢复 digest 坐标并复验。
- [x] 故障演练：fake codex binary → 离线 verify exit 1；Provider 7 不可达 → Task 544
      `protocol_error` 正确归类（已恢复端点）；不可达 daemon 连接检查 → 502。

### 生产签署前仍需执行（不阻塞本阶段 Git 交付）

- [ ] 在真实生产 Host 按 Runbook 重建冻结与证据批次，repo digest 以生产 registry 为准。
- [x] 关闭全部历史 Issue、drain 旧任务，切换窗口内无旧 Kit/旧镜像任务在途（dev 目标 Host 已执行）。
- [ ] 完成最小观察任务数与观察时间，记录基线/切换后指标并批准阈值（dev 观察窗口 Task 536–544 已记录，生产需重建）。
- [x] 完成回滚演练与 replacement Issue 流程（dev 目标 Host 已执行；生产四种故障场景仍按 Runbook 演练）。
- [ ] `credential_ref` 运行时接线、arm64 Kit 制品、私有 CA 与 Profile 级远程 Docker path
      部署配置（见总计划剩余已知项）。
