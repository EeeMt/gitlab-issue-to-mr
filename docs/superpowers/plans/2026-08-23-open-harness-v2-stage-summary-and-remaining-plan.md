# Open-Harness V2 遗留项与验收计划

**更新：** 2026-08-25
**状态：** Internal Preview；既有 L1/L2 证据基于 image-owned CLI，Worker Kit ownership 修正尚未实现

本文只记录遗留项，以及已完成但发布和验收时必须继续遵守的约束，不是提交历史或完整阶段台账。架构基线见[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md)，操作流程见[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md)。当前源码和 Runbook 仍有 image-owned CLI lock 的旧事实；完成下列 source correction 前，不得把它们解释为新的 Kit-owned 方案。

## 1. 方案修正与边界

目标 ownership：

- Project Runtime Image 只提供 Java、Node、Playwright 等项目工具链。
- Worker Kit 提供 launcher、Nix 工具链，以及 Pi/OpenCode/Claude/Codex 四个 Harness 的完整 inventory；构建时可指定携带的 CLI 集合，默认 `pi+opencode`，但 manifest 仍记录四个 key。每项标记 `availability=present|absent`；`absent` 必须带稳定 `reason_code`：未选择用 `not_selected`（预期、info），选择但缺 payload 用 `missing_payload`（warning、degraded），核验成功才标 `present`，不要求 absent 存在 payload、path、version 或 SHA。漏洞排除原因写入 release note/审计证据，不作为 manifest 运行状态。
- Runtime Bundle 提供 Task 冻结的 Adapter、Bridge 和编排 bytes。
- execution identity 绑定 `image_identity + kit_identity + bundle_digest`；baseline CLI version/SHA 不再作为 image 或 Task 的 hard gate。

Worker Kit 仍可通过显式 `host_mount` 作为 break-glass 路径，但必须是受审计的单一来源。禁止同一 Harness 在 image 与 Kit 之间隐式回退、混装或同时提供两个可选 payload。

构建选择集、实际 payload、manifest 和 archive 的变化必须产生新的 content-addressed Kit identity；禁止覆盖既有 Kit，也不能用选择集变化绕过完整性校验。

兼容性判定分三层，不能互相替代：

| 层级 | 检查内容 | 结果 |
| --- | --- | --- |
| Kit 制品完整性 | manifest、archive、content digest、platform，以及每项 present 的实际 path/bytes、权限和可执行性 | `not_selected` 且实际不存在记录 info；选中但缺 payload 为 `missing_payload`，只告警并生成 degraded Kit；absent 但仍有对应 payload/path，或 availability 与实际内容冲突，整 Kit fail closed；present 的文件缺失、不可执行或 self-integrity SHA 不符也整 Kit fail closed |
| Compatibility policy | Adapter tested/baseline version、file/layout SHA 与 observed inventory 的差异 | 任意差异均只输出脱敏 warning；小版本升级是预期场景，继续 verify/start |
| Functionality gate | 仅对 `present` CLI 执行 `--version`、self-check、Adapter smoke、协议握手和退出语义 | 失败只使该 Harness unavailable，不清空或阻断其他 Harness |

warning 字段按类型区分：present compatibility warning 必须带 Harness key、Kit identity、observed/baseline version 和 SHA；`missing_payload` warning 只带 Harness key、Kit identity、availability 和稳定的脱敏 reason，禁止伪造 version/SHA；`not_selected` 只记录 info。任何 warning 都不得包含 token、完整环境变量、payload、Provider response 或敏感诊断，也不改变已冻结的 Kit 来源或自动升级/回退 CLI。

Kit inventory 的 `file-or-layout SHA` 是 `present` CLI 实际内容的完整性证据；它不是 Adapter baseline 的兼容性硬门禁。运行时不按 semver major/minor/patch 分类 version 差异；任意 tested/baseline version 或 SHA 差异均继续 verify/start，并留下可复核的脱敏 warning。实际可执行性只由对应 Harness 的 functionality gate 决定。

Kit 构建选择集、inventory availability 与 `enabled_harnesses` 三者分离：构建选择集只决定尝试携带哪些 payload，enabled 只表示 Profile/产品允许选择，availability 表示本次 Kit 是否提供并通过验证。`absent` 不得自动从 image、`PATH` 或其他 Kit 回退；Task create/start/retry/resume/recovery 选择 absent Harness 时稳定拒绝 `harness_cli_unavailable`。旧 Kit 退役后的历史 retry/resume 同样只返回普通 `worker_kit_unavailable`。UI/catalog 必须展示 unavailable/disabled 及脱敏 reason。

漏洞处理保持简单：有修复版时构建新的不可变 Kit 并升级该 Harness CLI；暂时不要某 Harness 时从 build 集合排除它，并在 release note/审计证据记录原因。旧 Kit 不得原地修改；真有高危漏洞时管理员可直接删除整个旧 Worker Kit。运行中、retry/resume 失败可接受，走现有通用 `worker_kit_unavailable` 或正常执行失败，不新增任务迁移或专用错误码。

## 2. Source correction 遗留项（按依赖顺序）

- [ ] **修订架构合同与 Runbook：** 明确上述 ownership、Kit inventory、advisory compatibility、per-Harness unavailable functionality 和不可变 Kit/管理员高危删除规则；清理当前 image-owned lock 表述。
- [ ] **Kit 制品安装：** 以 content-addressed、atomic rename/no-replace、root-owned/不可覆盖目录安装 Kit；记录 Kit archive、manifest、content digest 和 platform。
- [ ] **Kit inventory 完整性：** 四个 key 都要记录 `availability` 和 absent `reason_code`；构建选择集未包含的 key 为 `not_selected`（预期、info），选择但 payload 缺失为 `missing_payload`（warning，Kit/Profile degraded），仅实际写入并核验成功的 payload 才能标 present。漏洞排除原因写入 release note/审计证据；absent 但仍有 payload/path 或 availability 与实际内容冲突，以及 present 的文件缺失、unsafe path、不可执行或 SHA 不符，均使整 Kit fail closed。
- [ ] **Compatibility policy：** Adapter 声明的 tested/baseline version/SHA 只作 advisory；任何 version/SHA 不匹配都只写脱敏 warning 并继续，不阻止 Profile verify 或 Task start；小版本升级是预期场景，运行时不做 semver 分类，也不要求重建 Project Runtime Image。
- [ ] **Functionality gate：** 仅对 present CLI 运行 `--version`、self-check 和 Adapter smoke；失败只标记该 Harness unavailable，不阻断其他 Harness，warning 不能掩盖实际不可用 CLI。
- [ ] **Identity 与 migration：** 增加 Kit identity/evidence，并以 `076_v2_worker_image_identity` 的后继 migration roll-forward；不得把 baseline CLI version/SHA 写回成 hard gate。
- [ ] **Registry 与路径：** 增加 `source=worker_kit`，Adapter 只使用冻结 Kit manifest 指定路径；保留显式 `host_mount` break-glass，禁止从 image/`PATH` 隐式 fallback。
- [ ] **启用与执行链：** 分离构建选择集、`enabled_harnesses` 和 availability；readiness、start、retry、resume、recovery、Profile verify 和 UI/catalog 都传播 unavailable/disabled reason，选择 absent 时返回稳定 `harness_cli_unavailable`。
- [ ] **漏洞处理：** 有修复版则构建新不可变 Kit 升级该 Harness；暂时不带某 Harness 则从 build 集合排除，并在 release note/审计证据记录原因。高危时允许管理员直接删除整个旧 Worker Kit；旧 Kit 不原地修改，失败走通用 `worker_kit_unavailable` 或正常执行失败。
- [ ] **移除旧链：** 删除 image 内 CLI payload、image CLI lock 和依赖其 SHA 的 verifier/preflight 链；Project Runtime Image 不再因 Kit CLI 版本差异而被要求重建。
- [ ] **发布与离线资产：** 修订 release overlay、offline bundle、preflight、worker entrypoint、Kit verifier、export manifest、UI/catalog 和 fixture；允许默认 `pi+opencode`、显式子集或 0–4 个 CLI payload，必须逐 key 记录构建选择、availability/reason，并重新生成不可变 Kit 和对应证据；高危时允许管理员删除整个旧 Kit，原因写 release note/审计证据。
- [ ] **重跑验收：** 完成后重跑本地 L1/L2、真实 Linux/PG、所有 enabled 且 present/available Harness 的 L3 export 与 L4 Host canary、Provider；Pi 20-task、Pi 默认切换和最终 `v2_only` 是 Pi 可用及全量切换门槛，不阻断 absent 或其他 Harness 的独立状态记录。

每个 source correction checkbox 都要留下 source commit、测试命令、Kit/image/Bundle digest 和脱敏日志路径；单元测试通过不能替代对应 Host 或真实 Task 证据。测试必须覆盖：默认集合、显式子集、0–4 payload、选择但缺 payload 的 degraded Kit、`not_selected` info 不阻断其他 Harness、present integrity fail closed、functionality 单 Harness 隔离、baseline mismatch warning、通用 `worker_kit_unavailable`、UI/catalog reason，以及 image/`PATH` 不回退；构建选择集不得被当作 `enabled_harnesses`。

## 3. 仍然有效的外部门禁

- [ ] 在可访问 PostgreSQL 上重跑 `test_068_migration.py`，并由唯一 migration owner 从实际 current revision 升级到精确 target；另行重跑锁顺序、CAS/generation 和并发测试。
- [ ] 在真实 Linux Host 验证 `renameat2(RENAME_NOREPLACE)`、fsync、目录冲突和崩溃恢复。
- [ ] 准备本轮 Kit-owned release 的默认集合、显式子集或 0–4 个 CLI payload、Kit/platform/content digest 和 Runtime Bundle；逐一记录四 key 的构建选择及 availability/reason。旧 image-owned CLI identity/lock 不得作为新 release evidence，但已核验、不可变且项目工具链未变的 Project Runtime Image 可以复用，并纳入新的 `image_identity + kit_identity + bundle_digest` 组合；漏洞原因和旧 Kit 管理员退役记录必须可审计。
- [ ] 对每个 enabled 且 present/available Harness 完成真实 Task 的 L3 DB-bound Bundle export；absent/unavailable Harness 不伪造 export，记录稳定 `harness_cli_unavailable` 和其余 Harness 的独立结果。
- [ ] 完成 Provider 授权、凭据轮换、secret scan、真实 remote Docker inspect，以及所有 enabled 且 present/available Harness 的 Host canary；absent Harness 只记录 `harness_cli_unavailable`。
- [ ] 对 enabled 且 present/available 的 Harness 按实际能力完成 Git commit/push/MR、失败/取消/timeout/recovery、session/Skills、usage、archive；OpenCode 仅在 present 时验证 server 生命周期，Pi 仅在 present 时验证 ACK/顺序/steering/follow-up。
- [ ] 对 Pi（仅在 Pi present/available 时）完成至少 20 个内部 Task、390×844/768px/桌面浏览器检查，以及可用 Linux/PG/AF_UNIX/scheduler 环境的 skip 重跑；这是 Pi acceptance 门槛，不阻断其他 Harness 的可用性结论。
- [ ] 维护窗口执行独立 hard cut 和 Pi 默认切换；这是全量切换门槛：`PENDING/QUEUED → CANCELLED`，`RUNNING recovery → stop container → FAILED`；V1 historical read 保留，V1 writer/execute/retry/resume/continue 拒绝。未满足时保持 `dual_canary`，不阻断其他 Harness 的独立验收。

以下输入必须来自同一个 Kit-owned release：Kit archive/manifest/content digest、构建选择集、四个 key 的 availability/reason、present CLI inventory、可复用或新建的 Project Runtime Image identity、Runtime Bundle digest、Adapter digest、Profile generation、Host/daemon identity 和 Task attempt。present compatibility warning 记录 observed/baseline version/SHA；`missing_payload` 记录 availability/reason warning，`not_selected` 记录 info；漏洞排除原因在 release note/审计证据中记录；应逐 Harness 记录 warning、unavailable 或 clean result。构建选择集不得替代 `enabled_harnesses`。

## 4. 已完成但必须备注的证据与约束

- `5b9ec15e`、`abb56ae3`、`cda8e6ee` 证明的是旧 image-owned CLI L1/L2 实现（统一制品验证、DB-bound export、identity/evidence/dual-canary/resume）；它们不是 Kit-owned source correction 的发布证据，迁移后必须全部重跑。
- 当前本地回归为 `2960 passed, 61 skipped, 2 deselected, 96 subtests`，明确排除了历史 `test_068_migration.py` 和 scheduler lifecycle；这不等于 L3/L4 通过。
- L1/L2 不等于 production proof；L3/L4 仅针对 enabled 且 present/available Harness，是制品、Host、Profile、Bundle 与真实 Task、事件、terminal、usage、Git/MR 和 archive 的绑定/对账；absent Harness 记录 `harness_cli_unavailable`，不伪造验收。
- dual-canary 保留 legacy V1 execution path；只有显式 V2 overlay 和完成新 Kit evidence 的 Profile 才能执行 V2。OMP 不进入本轮首发关键路径。
- Task、Profile、image、Kit、Bundle、Adapter bytes、protocol 和 evidence 必须来自同一冻结组合；identity/evidence 不一致时 fail closed，不回退 V1 或混用旧制品。
- Adapter settled 不等于 Task success；command `delivered` 只表示原生 ACK，`outcome_unknown` 不得重放，command history 不得泄露 payload、digest 或 native diagnostics。
- 不在 Git、manifest、日志或验收输出记录秘密；mutable tag、placeholder SHA、未核验或项目工具链已变化的 image，以及未经核验的 Kit manifest，不得冒充 release evidence。
- 旧 image-owned CLI identity/lock 不能作为新 release evidence、Kit identity、compatibility warning 或 L3/L4 release lock；已核验、不可变且项目工具链未变的 Project Runtime Image 可复用，并作为新组合的 `image_identity`。四个 Harness 的 availability/reason 必须逐 key 保留。
- `host_mount` break-glass 必须显式选择、逐 Harness 授权并记录来源；不得成为 image/Kit ownership 不清时的自动兜底。

## 5. 当前阻塞、执行顺序与停止条件

当前阻塞是 source correction、外部环境与发布权限，而非已知源码 P0/P1。顺序为：先修合同和 Kit 安装/identity，再修 registry 与全链路校验，随后移除 image CLI lock，重跑 L1/L2，最后依次执行 PG/Linux、release、L3、L4、acceptance 和 hard cut。

发布前的最低核对顺序是：

1. 校验 Kit archive、manifest、content digest、platform、构建选择集和四 key availability/reason；仅对 present key 校验实际 CLI inventory，并确认 absent 不存在对应 payload/path（选中但缺 payload 记录 `missing_payload` 并使 Kit/Profile degraded）。
2. 在目标 Host 安装并验证 root-owned content-addressed Kit，确认实际挂载路径。
3. 对 present key 运行 functionality gate；失败只标记该 Harness unavailable，再比较 baseline 并记录 advisory warning。
4. 绑定 Profile generation、image identity、Kit identity 和 Bundle digest。
5. 对 enabled 且 present/available 的 Harness 执行 fresh、retry、resume、recovery 和 delivery smoke；有效 Kit 选择 absent 时使用既定 `harness_cli_unavailable`，已删除 Kit 时使用通用 `worker_kit_unavailable`，或按正常执行失败处理；任何来源改变都重新 verify。

只有第 1–5 步全部完成，才可开始 enabled 且 present/available Harness 的 L3/L4；允许本轮 0–4 个 available CLI，但每个 Harness 的 warning、info、unavailable 或 clean 结果必须单独保留，不能聚合成全局“兼容通过”。

在 Kit-owned 方案、Provider 授权、PostgreSQL/AF_UNIX/Linux/remote Docker、真实测试仓库和不可变 release asset 到位前，不执行 `v2_only`、Pi 默认 migration、生产制品 push 或真实全量切换。Pi 不可用时只阻断 Pi 默认/20-task/hard-cut 门槛，不阻断其他 Harness 的独立验收。外部输入到位后先更新本 tracker 的 checkbox 和脱敏证据路径。

出现 Kit manifest/content/platform 不一致、identity/evidence 混搭、placeholder/mutable tag、Profile 未在目标 Host 验证、PG/AF_UNIX skip 未重跑、任一 enabled 且 available Harness 缺真实 Task/MR、secret scan/凭据轮换未完成或 migration owner 不唯一，立即停止。单个 present CLI 的 functionality 失败只将该 Harness 标为 unavailable；若因此没有可执行的 enabled Harness，再停止该 Profile。高危漏洞若仍使用旧 Kit，应由管理员删除旧 Kit；删除后的失败按通用 `worker_kit_unavailable` 或正常执行失败处理。硬切前保持 `dual_canary`，只回到已登记的不可变 image/Kit/Bundle 组合；数据库只 roll-forward，不修改历史 Snapshot、Issue 或证据。
