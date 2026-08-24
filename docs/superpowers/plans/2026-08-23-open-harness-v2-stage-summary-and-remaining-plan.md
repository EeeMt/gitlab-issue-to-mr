# Open-Harness V2 遗留项与验收计划

**更新：** 2026-08-24
**状态：** Internal Preview；源码与本地 L1/L2 已完成，真实发布与 Host 验收未完成

本文是后续执行 tracker，不是提交历史或完整阶段台账。只记录尚未关闭的外部门禁，以及已经完成但在发布、验收和后续维护中必须继续遵守的约束。架构基线见[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md)，操作流程见[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md)。

## 1. 当前结论

源码实现、重复实现收敛、V1 执行策略、冻结 Runtime Bundle、Worker identity/evidence、Pi command plane、DB-bound export、release preflight 和测试 fixture 已分批提交。关键实现提交为 `5b9ec15e`（统一制品验证）、`abb56ae3`（DB-bound Bundle export）和 `cda8e6ee`（冻结 identity/evidence、dual-canary、resume/release 边界）。

这只证明 L1/L2，不证明可发布或可硬切。当前不得把本地 fake Docker、离线 fixture、旧 remote image、direct Harness probe 或文档记录当作 L3/L4 证据。

## 2. 遗留外部门禁

以下项目仍未完成；每项必须保留独立、可脱敏、可复核的操作记录。

- [ ] **历史迁移回归：** 在可访问的 PostgreSQL 上重跑 `test_068_migration.py`，确认历史迁移测试结果；这不是 V2 发布迁移目标，也不能替代真实升级记录。
- [ ] **V2 migration 与并发：** 由唯一 migration owner 从实际 current revision 升级到经审的精确 V2 target（当前基线为 `076_v2_worker_image_identity`，或经审后的后继 revision），记录 `from/to`、owner、日志和结果；另行重跑锁顺序、CAS/generation 和并发测试。
- [ ] **真实 Linux 文件系统：** 在 Linux Host 验证 Runtime Bundle 导出的 `renameat2(RENAME_NOREPLACE)`、fsync、目标目录冲突和崩溃恢复语义。
- [ ] **真实 Docker identity：** 构建新的不可变 Worker image，记录 `repository@sha256`、image ID、Linux platform 和 CLI lock SHA；在目标 remote Docker daemon live inspect，并与 Profile、Bundle、Kit 对账。
- [ ] **真实 Kit/release lock：** 生成与 image、Runtime Bundle 和四个 CLI payload 完全匹配的 Worker Kit；记录 Kit version/digest/platform 和非占位 CLI version/SHA/payload。
- [ ] **四份 L3 export：** Pi、OpenCode、Claude、Codex 各使用一个已完成 Profile verify-runtime 的真实 Task，导出 DB-bound Runtime Bundle，并记录 Task、Harness、attempt、Bundle/Adapter/image/Kit digest。
- [ ] **Provider 与凭据：** 完成真实 Provider 授权和本轮曾使用凭据的轮换；保留不含秘密的 operator 记录，并对新制品、日志和验收输出执行 secret scan。
- [ ] **真实 Host canary：** 在同一冻结 release lock 上完成四个 Harness 的真实 Worker/Scheduler Task，覆盖 fresh、失败、取消/timeout、session/Skills、usage、archive 和 Git commit/push。
- [ ] **L4 delivery/MR：** 完成真实仓库修改、commit、push、创建/更新 MR 与归档对账；OpenCode 还需验证 server 生命周期，Pi 还需验证 native ACK、严格顺序、steering/follow-up、恢复和 terminal/cancel race。
- [ ] **Pi acceptance：** 使用冻结任务集完成至少 20 个同类内部 Task，保留全部原始样本（包括失败），并记录质量、时延、协议错误、资源、Git/MR 和 archive 指标。
- [ ] **产品验收：** 在 390×844、768px 和桌面 viewport 完成浏览器检查；在可用 Linux/PG 环境重跑 PostgreSQL、AF_UNIX 和 scheduler 相关 skip。
- [ ] **维护窗口与 hard cut：** 由唯一 migration owner 执行精确 `from/to` 升级；确认残留 V1 状态矩阵为：`PENDING/QUEUED` 取消，`RUNNING` recovery 不恢复而是停止容器并置为 `FAILED`，其余历史 V1 read 可用且 writer/execute/retry/resume/continue 被拒绝；再以 `AUTO_MIGRATE=false` 启动 `v2_only`，最后单独提交并执行新 Profile 默认 Pi 的变更。

远程 Docker、Provider、CLI payload、image RepoDigest 和真实 Task/MR 都必须来自本轮同一 release lock；旧环境的成功记录不能补足上述缺口。

## 3. 已完成但必须保留的约束

以下不是待办，但任何发布、修复或新提交都不得破坏：

- **证据边界：** 源码和本地测试属于 L1/L2，不是 production proof；L3 是制品/Host 安装验证，L4 是真实 Task/交付验收，L3 不等于 L4。
- **双 canary：** 基础 Compose 保留冻结的 legacy V1 execution path，且不加载 V2 release lock；只有显式 `deploy/docker-compose.v2-release.yml` overlay 才允许 V2 execution。未有冻结 V2 identity/evidence 的 Harness 不得路由到 V2。
- **V1 策略：** dual_canary 阶段保留 legacy V1 的执行能力；只有切到 `v2_only` 后，V1 历史 Task、日志、归档和统计继续可读，而 `create/execute/schedule/retry/resume/continue` 必须由中央策略在 API、Scheduler、Worker 和 recovery 全链路拒绝。OMP 不进入本轮首发关键路径。
- **迁移策略：** 只允许唯一 migration owner 从实际 current revision 升级到经审的精确 V2 target；V2 schema 采用 roll-forward-only，不用 downgrade 恢复 V1 物理 schema。hard cut 前保留明确 abort point。
- **冻结输入：** Task、Profile、Runtime Bundle、Adapter bytes、Worker image、Kit、CLI lock、model protocol 和 evidence 必须来自同一冻结身份；启动、retry、resume、recovery 发现不一致时 fail closed，不回退 V1 或混用旧制品。
- **完成语义：** Adapter settled 不等于 Task success；唯一 Task terminal、Canonical Event 顺序、Git/MR delivery、usage、Skills 和 archive 必须由 Codify 公共链路完成并对账。
- **控制语义：** command `delivered` 只表示 Harness 原生 ACK，不表示模型已执行；`outcome_unknown` 不得重放；command history 只返回公开状态和稳定拒绝原因，不暴露 payload、digest 或 native diagnostics。
- **凭据与制品：** 不在 Git、manifest、日志或 acceptance 输出记录秘密；mutable tag、placeholder SHA、旧 image、Kit manifest 冒充 Runtime Bundle，均必须 fail closed。
- **变更纪律：** Pi 默认 migration、`v2_only` hard cut、Provider/CLI/image/Kit release lock 必须分别提交、分别验收、分别记录维护窗口；新增协议能力前先补合同、fixture 和真实 endpoint/Host smoke。

## 4. 当前可信证据（最小摘要）

- `5b9ec15e`：统一 Kit/Runtime Bundle/image artifact 验证，缺失或不匹配时 fail closed。
- `abb56ae3`：按 Task 或 Bundle digest 从数据库导出冻结 V2 Bundle；已覆盖 canonical manifest、archive、sidecar digest 和安全写入边界，但未完成真实 Linux/PG/L3 验收。
- `cda8e6ee`：V2 Task 绑定 Worker identity、Profile evidence、Adapter version/digest 和冻结 Bundle；dual-canary、resume 和 release preflight 边界已落地。
- 本地后端回归：`backend/.venv/bin/python -m pytest backend/tests/unit -q --ignore=backend/tests/unit/test_068_migration.py -k 'not test_scheduler_service_lifecycle'`，`2960 passed, 61 skipped, 2 deselected, 9 warnings, 96 subtests passed`。该命令明确排除了历史 `test_068_migration.py`；skip 和 deselect 仍是外部环境待验收项，不能解释为 L3/L4 通过，且 `test_068_migration.py` 必须在真实 PostgreSQL 上单独重跑。
- 其他可信入口：架构中的[协议与冻结制品合同](../../architecture/open-harness-v2.md)，Runbook 中的[发布冻结清单](../../runbooks/multi-harness-rollout.md)与[真实验收矩阵](../../runbooks/multi-harness-rollout.md)。

正式 L3/L4 证据至少要记录：source commit、Runtime Bundle digest、image `repository@sha256`、Kit version/digest/platform、四个 CLI version/SHA、Profile/Host verify 结果、Task/attempt/project/MR 标识、Provider protocol、测试 skip/failure 和脱敏 acceptance report 路径。

## 5. 按依赖排序的下一步

1. **准备权限与环境。** 完成 Provider 授权/凭据轮换，准备可访问 PostgreSQL、允许 AF_UNIX 的 Linux 环境和目标 remote Docker daemon。完成标准：外部责任人、权限边界和脱敏记录齐全。
2. **关闭基础环境门禁。** 单独重跑 `test_068_migration.py`；由唯一 owner 从实际 current revision 升级到精确 V2 target（当前基线 `076_v2_worker_image_identity` 或经审后继），记录 `from/to`；再重跑锁/CAS/并发、scheduler/AF_UNIX，并验证 Linux `renameat2`/fsync。完成标准：无未解释失败，所有 skip 有真实环境结果，且历史 068 回归不被误写成 V2 migration 执行记录。
3. **冻结发布制品。** 准备四个真实 CLI payload、不可变 image、Kit、Runtime Bundle 和 release lock。完成标准：版本、SHA、platform、RepoDigest、Adapter digest 和 lock 全部可交叉复核，禁止 placeholder/mutable tag。
4. **完成 L3。** 逐 Host 执行 Kit/image/Bundle/Profile verify-runtime；为四个 Harness 各导出一个已验证 Task 的 DB-bound Bundle。完成标准：四份归档及 identity/evidence 对账记录齐全。
5. **完成 L4 canary。** 执行四个真实 Task/MR smoke、失败/取消/恢复路径、Pi command plane 和 OpenCode 生命周期。完成标准：事件、terminal、usage、Skills、Git/MR、archive 与 Host/lock 一一对应。
6. **完成 acceptance 与产品检查。** 执行 Pi 20-task 样本和浏览器验收，保存完整原始样本。完成标准：无阻断指标，失败样本未被删除；仅针对即将启用的 `v2_only`，V1 historical read 可用、V1 writers 被拒绝，command history 脱敏可复核。
7. **执行独立 hard cut。** 维护窗口中 drain V1、执行精确 migration、启动 `v2_only`，再单独切换新 Profile 默认 Pi。完成标准：残留 V1 状态矩阵为 `PENDING/QUEUED → CANCELLED`、`RUNNING recovery → stop container → FAILED`；V1 historical read 可用，API/Scheduler/Worker/recovery 的 create/execute/schedule/retry/resume/continue 被拒绝；migration owner、服务启动参数、监控、回滚坐标和签署记录齐全。

任何一步失败都停止推进，保留失败 Task、raw event、制品 digest 和日志；只允许回到已登记的不可变 image/Kit/Bundle 组合，不允许混搭或修改历史记录制造通过证据。

## 6. 阻塞与所需输入

- 当前阻塞是外部环境与发布权限，不是已知源码 P0/P1：需要 PostgreSQL/AF_UNIX/Linux/remote Docker 实际环境、Provider 授权、四个 CLI payload、image/Kit 构建权限和真实测试仓库/MR 权限。
- 在上述输入到位前，不执行 `v2_only`、Pi 默认 migration、生产制品 push 或真实全量切换。
- 外部输入到位后，先更新本 tracker 的对应 checkbox 和证据路径，再推进下一依赖步骤；不要恢复提交流水账或把测试数量扩写成历史台账。

## 7. 停止条件与回滚

出现以下任一情况立即停止：identity/evidence/lock 不一致；制品使用 placeholder 或 mutable tag；Profile verify 不在目标 Host 执行；PG/AF_UNIX skip 未重跑；command ACK/terminal/cancel race 无法对账；四 Harness 任一缺真实 Task/MR、usage 或 archive；凭据轮换或 secret scan 未完成；migration owner 不唯一；切到 `v2_only` 后仍有 V1 writer 可执行。

硬切前保持 `dual_canary`，失败 Profile 停止接收新 Task，回到已登记的 legacy Profile。数据库只 roll-forward；不使用 downgrade 恢复 V1 schema。回滚不得修改既有 Task Snapshot、Issue 或历史证据。
