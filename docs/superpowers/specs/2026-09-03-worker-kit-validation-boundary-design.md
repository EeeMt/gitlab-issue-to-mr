# Worker Kit 可信安装与 Task 启动校验边界设计

**Date:** 2026-09-03

**Status:** Accepted — implementation complete; R4/L5 acceptance pending

**Scope:** Open-Harness V2、`mounted_kit`、Worker Kit 构建/安装、Profile Verify、Task Snapshot、Scheduler claim、Worker container start

**Related:** [Task #348 启动前延迟调查](../evidence/2026-09-02-task-348-startup-delay.md)、[Worker Profile 共享配置与运行时就绪设计](2026-08-14-worker-profile-shared-configuration-design.md)、[Worker Kits](../../worker-kits.md)、[Open-Harness V2 阶段结论与剩余验收计划](../plans/2026-08-23-open-harness-v2-stage-summary-and-remaining-plan.md)

Implementation and current Host evidence: [R4.1/R4.2 Kit boundary candidate evidence](../evidence/2026-09-03-open-harness-v2-r4.1-kit-boundary.md).

## 1. 决策

Open-Harness V2 采用 **可信管理员 + content-addressed 不可覆盖安装** 的 Worker Kit 运维模型。

完整内容校验只在以下三个边界执行：

1. Kit 构建/导出；
2. 目标 Host 安装；
3. 管理员显式执行 Profile 或历史 Task Runtime Verify。

正常 Task 启动路径不再通过 Docker archive 重复读取和哈希完整 Kit，也不再对未选择的 Harness、完整
Nix closure 或其他 Kit 文件做逐 Task 内容扫描。Task 启动只校验创建时冻结的 Kit manifest identity 和
当前 Task 选择的 Harness identity，并继续验证 Runtime Bundle、Adapter、image 和 execution contract。

本决策不引入 `strict/trusted` 双模式、兼容开关、新 Task 状态或新数据库 schema。V2 只有一套发布规则：
不满足可信安装约束的 Kit 不能通过 V2 `verify-runtime`，而不是回退到昂贵的逐 Task 全量校验。

## 2. 背景与证据

Task #348 在 warm Scheduler、无并发排队、仓库准备约 1.2 秒的情况下，从创建到 canonical
`run.started` 约 130.1 秒。其中三个控制面完整 Kit 校验分别约 39.0、38.6 和 38.0 秒，合计约
115.6 秒，占启动前总时间约 89%。真正的 Harness/模型执行约 32.8 秒。

当前实现的正常 V2 Task 实际穿过四层 Kit 内容校验：

| 层级 | 当前行为 | Task #348 可见成本 |
| --- | --- | ---: |
| Scheduler claim 前 | 创建停止态 probe container，通过 Docker archive 扫描和哈希完整 Kit | 约 39.0 秒 |
| Worker 准备执行上下文 | 再次执行同一 deterministic full probe | 约 38.6 秒 |
| 真实 Task container start 前 | 对实际 stopped container 的只读挂载再次扫描完整 Kit | 约 38.0 秒 |
| Kit launcher | `verifyKitContent()` 再次遍历完整 content inventory | 包含在约 12.5 秒容器入口阶段 |

前三层主要开销来自远端 Docker archive、tar 解包和 Backend Python SHA-256；第四层直接读取容器文件系统，
成本较低但仍重复验证同一安装身份。readiness TTL 不能缓解前三层开销，因为当前 V2 Scheduler 和 Worker
明确拒绝把有效 `ready` 结果作为执行许可。

该实现是在“Kit 路径可能被任意原地替换”的假设下关闭 probe-to-container 时间窗口。实际发布链路已经采用
更强、也更便宜的控制：构建产物和安装目录 content-addressed，安装过程完整验证、禁止覆盖、原子发布，
Task container 只读挂载。继续在每个 Task 内重复证明全部字节没有变化，与当前可信运维模型不匹配。

## 3. 可信边界

### 3.1 受信任主体

以下主体属于同一受信任运维边界：

- Codify 管理员：维护共享 Worker 配置、Worker Profile 和 Runtime Verify；
- Worker Host root 管理员：安装、保留和退役 Worker Kit；
- 目标 Docker daemon：创建 Worker container 并提供只读 bind mount；
- 发布负责人：冻结最终 Image、Kit、Profile、Runtime Bundle 和目标 Host identity。

普通用户、Task 内 Harness/模型进程和项目代码不属于受信任主体。它们不能写入宿主机 Kit 目录，Task
container 只获得只读挂载。

若 Worker Host root 或 Docker daemon 被恶意控制，攻击者同时可以替换镜像、挂载、容器和 Docker API
观察结果。应用层逐 Task 重复哈希不能在这个前提下建立独立信任根，因此 root/daemon compromise 不作为
逐 Task 全量校验的目标。

### 3.2 V2 Kit 必须满足的安装不变量

V2 `mounted_kit` Profile 必须同时满足：

1. Kit 由仓库提供的安装脚本安装，不能手工展开到普通目录；
2. archive 名和安装目录名包含 Kit version、platform 和 manifest SHA-256 前缀；
3. archive checksum、manifest、content inventory、Harness inventory 和安装后目录内容已完整校验；
4. 安装目录及父目录 root-owned，group/others 不可写；
5. 同一 identity 目录已存在时拒绝覆盖，发布通过 staging + 原子 rename 完成；
6. Profile 保存精确 identity 目录，禁止 `/current`、可变软链接或不带 digest 的别名；
7. Task container 对 Kit 根目录和 Kit Nix store 均使用只读挂载；
8. Kit 升级创建新 identity 目录，不原地修改旧目录；
9. 只要仍有 PENDING/QUEUED/RUNNING Task Snapshot 引用旧 identity，管理员就不得退役该目录；
10. 退役和异常修复由管理员显式操作，不由 Task 执行路径自动改写 Kit。

当前安装脚本已经实现 archive/content 校验、root ownership、禁止覆盖和原子 rename；实现本决策时需要把
“V2 Profile 只能使用 installer-managed content-addressed 路径”收进 Backend Verify 门禁，而不能只依赖
路径是绝对路径这一静态检查。

### 3.3 接受的剩余风险

本决策明确接受以下剩余风险：

- root 管理员绕过安装脚本并原地修改 payload；
- Host 文件系统静默损坏但 manifest 和所选 Harness 文件仍可读；
- 管理员在仍有旧 Task 引用时提前删除旧 Kit；
- Docker daemon 返回不可信挂载或文件观察。

这些情况分别属于受信任主体违规、Host/daemon 故障或运维错误。正常 Task 必须在 mount、manifest、所选
Harness 或 launcher 失败时 fail closed，但系统不为这些低频情况在每次 Task 启动支付完整 Kit 扫描成本。

## 4. 目标与非目标

### 4.1 目标

1. 把成功 Task 热路径上的完整 Kit 扫描从四层收敛为零；
2. 保留从构建产物到 Host 安装、Profile 验证和 Task Snapshot 的可追溯 identity；
3. Task 启动仍在执行 Harness 前发现错误 manifest、错误平台、错误版本和所选 CLI 缺失/篡改；
4. 已知不可用 Kit 继续阻止新建/重试并阻塞未领取 Task；
5. 配置变化继续使 Profile 验证证据失效，既有 Task Snapshot 不漂移；
6. 不影响 V1、`baked_image`、Runtime Bundle、command plane、canonical event 或 Provider 协议语义；
7. 用可复核的 warm-start cohort 证明启动延迟已经消除，而不重复正式 20-scenario benchmark。

### 4.2 非目标

- 不建立独立 PKI、签名服务、TPM 或远程证明；
- 不防御恶意 Worker Host root 或恶意 Docker daemon；
- 不新增后台周期性全盘 Kit 审计；
- 不新增 `strict_probe`/`trusted_install` 配置开关；
- 不把 readiness 改成 Worker Pool 健康系统；
- 不修改历史 Task Snapshot、Runtime Bundle 或 benchmark 记录；
- 不自动迁移引用旧 Kit 的 Task；
- 不因本决策重跑与启动边界无关的协议矩阵或正式 benchmark。

## 5. 校验职责重新分配

### 5.1 构建与导出：完整内容权威

Kit 构建/导出继续负责：

- 生成 canonical `content_inventory`；
- 对所有 execution-bearing 文件记录 path、size 和 SHA-256；
- 对四个 Harness 明确记录 `present` 或 `absent`；
- 验证 present payload 可执行、版本与 pinned version 一致；
- 生成 manifest SHA-256，并把前缀写入 archive 名；
- 拒绝覆盖已存在的同名 content-addressed archive。

构建产物的 manifest 是 Kit identity 权威。Adapter 声明、Kit inventory 和实际 payload 在这一层闭合。

### 5.2 Host 安装：完整字节与发布原子性权威

安装继续执行两次完整校验：解包前校验 archive，staging 解包后校验目录。只有全部通过后才写安装 receipt、
修正 ownership/mode，并原子 rename 到最终 identity 路径。

安装完成后同一 identity 路径不可覆盖。升级、修复或重新打包必须产生新 manifest digest 和新目录。

### 5.3 管理员 Verify：目标 Host 与 Profile composition 权威

`POST /api/worker-profiles/{id}/verify-runtime` 继续是完整远端验证入口，并且只允许管理员调用。它必须：

1. 解析共享配置与 Profile；
2. 确认 Kit 路径符合 content-addressed 命名且不是 symlink/别名；
3. 读取并核对 install receipt、manifest identity、platform 和 version；
4. 对完整 Kit 执行一次 content inventory 校验；
5. 对每个启用的 V2 Harness 执行 Profile-specific smoke；
6. 冻结 image identity、Kit identity、Harness inventory 和验证 generation；
7. 在 Docker I/O 结束后重新比较当前 Profile/shared verification digest，拒绝迟到结果；
8. 配置、目标 Host、image、Kit 或 Harness 变化时使验证证据失效。

`POST /api/tasks/{task_id}/verify-worker-runtime` 继续用于管理员显式验证历史 Snapshot 指向的旧 Kit。两种
Verify 都可以耗时，因为它们是低频、显式运维操作，不在普通 Task 启动关键路径上。

### 5.4 Task 创建：冻结执行所需的最小 Kit 事实

V2 Task 创建只能使用当前有效的 Profile 验证证据。创建事务必须把以下事实写入不可变 Snapshot/Bundle：

- `worker_kit_version`、精确 `worker_kit_path` 和 `runtime_locator_fingerprint`；
- `worker_kit_identity`：schema、version、platform、完整 manifest SHA-256；
- 所选 Harness 的 `cli_source`；
- 对 `worker_kit` source，从已验证 inventory 自动冻结 `cli_executable_path`、`cli_version` 和
  `cli_binary_digest`；
- Worker image identity、Adapter identity、Harness verification evidence 和 Runtime Bundle digest。

现有 `TaskWorkerProfileSnapshot.cli_executable_path`、`cli_version`、`cli_binary_digest` 和
`harness_config_snapshot.worker_kit_identity` 足以承载这些事实，不增加数据库字段。

Task 创建不得在 Profile payload 中要求管理员手工重复填写 worker-kit CLI path/digest；它们来自管理员
Verify 已确认的 manifest inventory。缺少任一必需事实时，V2 Task 创建 fail closed。

### 5.5 Scheduler：调度状态，不再证明完整内容

Scheduler 对 V2 mounted Kit 的职责调整为：

- `unavailable`：继续阻止创建/重试；未领取 Task 保持或退回 `PENDING`；
- 未过期 `ready`：允许继续领取；
- 无记录、`unknown` 或已过期 `ready`：只要 Task Snapshot 具有完整、有效的冻结 V2 identity，允许继续领取，
  不在 claim 前运行完整 probe；
- Snapshot identity 不完整或合同不匹配：fail closed；
- Docker target 连接错误继续使用现有 transient/recovery 语义，不伪装成 Kit 内容错误。

readiness 仍是共享的运维观察和已知失败门禁，但不再是每次执行的内容证明。TTL 到期表示观察不新鲜，
不表示 content-addressed 安装在后台自动变异，也不触发逐 Task 全量扫描。

### 5.6 Worker 与 launcher：实际挂载上的轻量 fail-closed

Worker 创建真实 Task container 时：

1. 不再执行第二次 `run_deterministic_kit_probe()`；
2. 不再通过 `inspect_mounted_kit_container()` 对 stopped container 读取完整 archive；
3. 从 Task Snapshot 使用冻结的所选 CLI path/version/digest，不从最新 readiness 或可编辑 Profile 重新解析；
4. 继续把 Kit 和 Nix store 只读挂载；
5. 继续在启动前物化并校验冻结的 Runtime Bundle；
6. 把 manifest SHA、Kit version、所选 CLI path/digest 传给 launcher。

正常 Task 启动时 launcher 只执行：

- 读取并解析小型 `manifest.json`；
- 比较 manifest SHA-256、Kit version 和 runtime platform；
- 确认 launcher/entrypoint、runtime bin 和所选 CLI 路径存在且可执行；
- 只对当前 Task 选择的 CLI 文件计算一次 SHA-256，并与 Snapshot digest 比较；
- 校验 Runtime Bundle manifest、files、contract、event schema 和 Adapter binding；
- 在全部通过后 exec Harness entrypoint。

launcher 的完整 `verifyKitContent()` 只在管理员 `--verify` 或安装/发布校验路径执行。正常 Task 不扫描未选择
Harness、完整 Nix closure 或其他 content inventory 文件。

## 6. readiness 与失败语义

| 条件 | 创建/重试 | Scheduler | Worker start | 持久化结果 |
| --- | --- | --- | --- | --- |
| Profile 验证证据缺失或已失效 | 拒绝 V2 Task | 不应存在新 Task | 不执行 | Profile 保持未验证 |
| readiness=`unavailable` | `409` | 保持/退回 `PENDING` | 不执行 | 保留确定性失败 |
| readiness=`ready` | 允许 | 允许 | 轻量校验 | 不逐 Task 刷新 TTL |
| readiness=`unknown`/过期，Snapshot identity 完整 | 允许 | 允许 | 轻量校验 | 保持 unknown，等待显式 Verify |
| Kit mount/manifest/version/platform 不匹配 | 已创建 Task 不改写 Snapshot | 已领取 | Harness 前失败 | 写稳定 Kit 错误并标记 unavailable |
| 所选 Harness 缺失、不可执行或 digest 不匹配 | 已创建 Task 不改写 Snapshot | 已领取 | Harness 前失败 | 写 `harness_cli_unavailable` 或 identity mismatch |
| Docker daemon 暂时不可达 | 不凭此删除 readiness 结论 | 使用既有 transient/recovery | 不执行 | 不写 deterministic unavailable |

实际容器已经提供比独立 probe 更直接的挂载证据。若 mount 或 launcher 产生确定性 Kit 错误，Worker 可以用
稳定错误码更新 readiness；不为了分类错误再同步运行一次完整 probe。管理员需要更详细诊断时显式执行 Verify。

## 7. 数据与接口影响

### 7.1 不需要数据库迁移

本决策复用：

- `worker_profiles.worker_kit_identity` 与 generation；
- `worker_profiles.v2_harness_verification_evidence`；
- `task_worker_profile_snapshots.runtime_locator_fingerprint`；
- `task_worker_profile_snapshots.cli_source`；
- `task_worker_profile_snapshots.cli_executable_path`；
- `task_worker_profile_snapshots.cli_version`；
- `task_worker_profile_snapshots.cli_binary_digest`；
- `task_worker_profile_snapshots.harness_config_snapshot`；
- `worker_runtime_readiness`。

不修改历史 Snapshot。旧 Snapshot 如果缺少本决策要求的 V2 CLI/Kit identity，不能被当前 V2 执行路径猜测补齐；
管理员可以关闭该 Task，或者按历史 Snapshot 显式 Verify 后用既有重试/重建路径创建完整的新 Snapshot。

### 7.2 API 行为

- Profile `verify-runtime` 增加 content-addressed install provenance 校验；
- Task create/update/retry 在 V2 writer 边界验证冻结的 Kit 和所选 CLI identity；
- Task runtime Verify 仍执行完整检查；
- readiness API 继续返回 `status`、`checked_at`、`ready_until`、inventory 和 Kit identity；
- UI 把过期 `ready` 展示为“验证观察已过期/建议重新验证”，不能描述为每个 Task 必须重新扫描；
- 已知 `unavailable` 的创建与调度行为保持不变。

## 8. 实施工作包

### W1 — 收紧可信安装门禁

- 在 V2 Profile Verify 中检查 content-addressed 路径、install receipt、manifest digest、version 和 platform；
- 拒绝 symlink、mutable alias、不带 digest 的普通目录和 receipt/manifest 不一致；
- 保留 V1 与 `baked_image` 现有行为。

### W2 — 冻结所选 Harness identity

- 从成功 Verify 的 inventory 解析所选 Harness；
- 在所有 Task writer（create、switch、retry/clone、CI repair）中保存或复制 CLI path/version/digest；
- writer 结束前统一验证 Snapshot、Bundle、Kit、image、Adapter 和 Harness evidence。

### W3 — 移除 Scheduler/Worker 全量热路径 probe

- V2 cached ready 不再强制 re-probe；
- unknown/expired 对完整 V2 Snapshot 不触发 full probe；
- 移除 Worker 创建容器前第二次 full probe；
- 移除 stopped Task container 的 full archive inspection；
- 保留 known-unavailable、transient Docker 和 recovery 语义。

### W4 — 收敛 launcher 校验

- 正常 Task 只校验 manifest、平台、版本、所选 CLI 和 Runtime Bundle；
- 完整 content inventory 仅在 `--verify` 路径执行；
- 四 Harness 使用同一 selected-CLI digest 规则；
- 失败发生在 Harness exec 前，并输出可稳定分类的非敏感错误。

### W5 — 测试与可观测性

- 为 build/install/admin Verify/full check 与 Task lightweight check 分开测试；
- 记录 `task_claimed`、`container_created`、`container_started`、`run.started` 分阶段耗时；
- 记录 Task 热路径是否错误调用 full probe；
- 不记录 Host secret、环境变量值、TLS 私钥路径内容或完整绝对诊断。

### W6 — 真实 Host 验收

- 在当前 `linux/amd64` release candidate 上重新生成 immutable Kit identity；
- 管理员完整 Verify 四 Harness；
- 执行 warm-start cohort 和每 Harness 最小 smoke；
- 形成独立 L2/L3/L4 evidence，再进入 R4 go/no-go。

## 9. 测试与验收

### 9.1 聚焦测试

必须覆盖：

- 非 content-addressed V2 Kit path、symlink、错误 receipt 和 digest mismatch 被 Verify 拒绝；
- 安装脚本仍拒绝覆盖，完整 content verification 仍能发现任一文件变化；
- Profile/shared execution input 变化使验证证据失效；
- Task Snapshot 自动冻结 worker-kit CLI path/version/digest；
- retry/clone 复制旧 Snapshot identity，不读取当前 Profile；
- V2 `ready`、`unknown` 和过期状态都不会在成功 Task 路径触发 full probe；
- `unavailable` 仍阻止创建/重试并阻塞调度；
- Worker 不调用第二次 full probe 或 stopped-container full inspection；
- launcher 正常 Task 不运行完整 content inventory 校验；
- launcher 对 manifest、platform、version、所选 CLI digest mismatch fail closed；
- 管理员 `--verify` 仍扫描完整 Kit 并运行四 Harness smoke；
- V1、`baked_image`、`host_mount`、Runtime Bundle 和 command plane 无回归。

### 9.2 真实 Host 性能门槛

在相同 Host、warm image、无并发排队、同一 verified Profile 上执行至少 5 个 V2 Task：

1. 成功 Task 热路径不得出现完整 Kit archive/content inventory probe；
2. `created_at -> Scheduler 开始处理` 保持秒级；
3. `created_at -> run.started` 中位数不超过 30 秒，单个不超过 45 秒；
4. 记录 container create/start、repository prepare、launcher lightweight check 和 control endpoint 分段耗时；
5. 四 Harness 各至少一个最小真实成功 smoke；
6. manifest mismatch、所选 CLI digest mismatch、Kit path 缺失各至少一个受控失败样本；
7. 所有失败都发生在 Harness 执行前，无错误成功、隐式回退或错误 Provider 请求。

性能门槛只约束 warm-start 系统开销。镜像首次拉取、目标仓库网络、模型首 token 和 Provider rate limit 必须
单独计时，不得混入 Kit 校验回归判断。

## 10. 发布与证据影响

本决策会改变 Kit launcher 和控制面启动路径，因此实现后必须生成新 Kit identity，并更新 L2/L3 和受影响
的 L4 startup evidence。R1–R3 的协议、生命周期和正式 benchmark 结论不因设计文档本身重新打开。

若实现严格限定为校验边界变化，并且 Harness CLI payload、Adapter/Bridge、Runtime Bundle、Provider
protocol/model 和 canonical event 语义均未变化，则只需：

- 聚焦 backend/launcher/install tests；
- 新 Kit 的完整 install + Profile Verify；
- warm-start cohort；
- 四 Harness 最小 release smoke；
- 失败分类和 V1 只读边界复核。

不重跑 20-scenario formal benchmark，也不清零已冻结协议矩阵。若实现过程中同时改变任一 CLI、Adapter、
Bundle、协议或事件语义，则按总计划的证据失效规则补跑实际受影响的 R2/R3 项。

## 11. 取舍

获得：

- 正常 Task 消除约两分钟的重复启动开销；
- readiness TTL 恢复为运维观察，而不是高成本逐 Task 授权；
- 信任边界与现有 content-addressed 安装事实一致；
- 完整校验集中在低频、可审计的管理员操作；
- 启动失败更接近实际挂载，减少 probe container 与 Task container 的重复路径。

付出：

- 不再逐 Task 发现未选择 Harness 或 Nix closure 的静默损坏；
- root 绕过安装规则后，系统只保证 manifest 和当前所选 CLI 的启动前校验；
- Kit 被管理员提前删除时，Task 会在实际 container start 而不是 Scheduler pre-claim 阶段失败；
- readiness 过期不再自动触发新鲜完整内容证明。

这些取舍在“管理员维护 Backend 配置和 Worker Host、Kit 通过 content-addressed 安装发布”的既定前提下可接受。

## 12. 决策优先级与退出条件

对 V2 installer-managed `mounted_kit`，本文件取代
[共享配置设计](2026-08-14-worker-profile-shared-configuration-design.md) 中要求 Scheduler 在 unknown/TTL
过期时执行完整 Kit probe、容器错误后同步严格复查，以及把该 probe 作为每次执行许可的相关条款。
共享配置继承、Snapshot 不可变、generation/CAS 写入、known-unavailable 门禁和管理员 Verify 设计继续有效。

本决策只有在以下条件全部满足后才算实现完成：

1. 可信安装约束已由 Backend Verify 门禁执行；
2. Task Snapshot 冻结完整 Kit 和 selected-Harness identity；
3. 正常 Scheduler/Worker/launcher 路径没有完整 Kit 扫描；
4. 管理员 Verify 仍执行完整内容与四 Harness smoke；
5. 真实 Host 性能和受控失败门槛通过；
6. 新 Kit identity、测试和 L2/L3/L4 evidence 可追溯；
7. 无 P0/P1、错误成功、隐式回退、凭据泄漏或历史 Snapshot 改写。

在上述条件关闭前，Open-Harness V2 保持 `dual_canary`，不得进入 R5/L6 hard cut。
