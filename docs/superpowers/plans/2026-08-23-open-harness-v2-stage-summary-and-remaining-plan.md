# Open-Harness V2 遗留项与验收计划

**更新：** 2026-08-25
**状态：** Internal Preview；既有 L1/L2 证据基于 image-owned CLI，Worker Kit ownership 修正尚未实现

本文只记录遗留项，以及已完成但发布和验收时必须继续遵守的约束，不是提交历史或完整阶段台账。架构基线见[Open-Harness V2 架构方案](../../architecture/open-harness-v2.md)，操作流程见[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md)。当前源码和 Runbook 仍有 image-owned CLI lock 的旧事实；完成下列 source correction 前，不得把它们解释为新的 Kit-owned 方案。

## 1. 方案修正与边界

目标 ownership：

- Project Runtime Image 只提供 Java、Node、Playwright 等项目工具链。
- Worker Kit 提供 launcher、Nix 工具链、Pi/OpenCode/Claude/Codex 四个 CLI payload，以及记录实际内容的完整 inventory。
- Runtime Bundle 提供 Task 冻结的 Adapter、Bridge 和编排 bytes。
- execution identity 绑定 `image_identity + kit_identity + bundle_digest`；baseline CLI version/SHA 不再作为 image 或 Task 的 hard gate。

Worker Kit 仍可通过显式 `host_mount` 作为 break-glass 路径，但必须是受审计的单一来源。禁止同一 Harness 在 image 与 Kit 之间隐式回退、混装或同时提供两个可选 payload。

兼容性判定分三层，不能互相替代：

| 层级 | 检查内容 | 结果 |
| --- | --- | --- |
| Kit 制品完整性 | manifest、archive、content digest、实际 path/bytes、platform、权限和可执行性 | 任何不一致或危险路径均 fail closed |
| Compatibility policy | Adapter tested/baseline version、file/layout SHA 与 observed inventory 的差异 | 任意差异均只输出脱敏 warning；小版本升级是预期场景，继续 verify/start |
| Functionality gate | CLI `--version`、self-check、Adapter smoke、协议握手和退出语义 | 任一失败均 fail closed |

`warning` 必须带 Harness key、Kit identity、observed version/SHA 和 baseline 字段，但不得包含 token、完整环境变量、payload、Provider response 或敏感诊断。warning 不改变已冻结的 Kit 来源，也不自动升级或回退 CLI。

Kit inventory 的 `file-or-layout SHA` 是 Kit 实际内容的完整性证据；它不是 Adapter baseline 的兼容性硬门禁。运行时不按 semver major/minor/patch 分类 version 差异；任意 tested/baseline version 或 SHA 差异均继续 verify/start，并留下可复核的脱敏 warning。实际可执行性只由 functionality gate 决定。

## 2. Source correction 遗留项（按依赖顺序）

- [ ] **修订架构合同与 Runbook：** 明确上述 ownership、Kit inventory、advisory compatibility 和 fail-closed functionality 规则；清理当前 image-owned lock 表述。
- [ ] **Kit 制品安装：** 以 content-addressed、atomic rename/no-replace、root-owned/不可覆盖目录安装 Kit；记录 Kit archive、manifest、content digest 和 platform。
- [ ] **Kit inventory 完整性：** manifest 必须记录实际 `key/path/observed version/file-or-layout SHA/platform`，并与 Kit 内实际 payload 一致；缺失、unsafe path、不可执行、platform 不符、manifest/archive/content digest 不一致仍 fail closed。
- [ ] **Compatibility policy：** Adapter 声明的 tested/baseline version/SHA 只作 advisory；任何 version/SHA 不匹配都只写脱敏 warning 并继续，不阻止 Profile verify 或 Task start；小版本升级是预期场景，且不要求重建 Project Runtime Image。运行时不做 semver major/minor/patch 分类。
- [ ] **Functionality gate：** CLI `--version`、self-check 或 Adapter smoke 失败仍 fail closed；warning 不能掩盖实际不可用的 CLI。
- [ ] **Identity 与 migration：** 增加 Kit identity/evidence，并以 `076_v2_worker_image_identity` 的后继 migration roll-forward；不得把 baseline CLI version/SHA 写回成 hard gate。
- [ ] **Registry 与路径：** 增加 `source=worker_kit`，Adapter 只使用冻结 Kit manifest 指定路径；保留显式 `host_mount` break-glass，禁止 image/Kit fallback。
- [ ] **执行链：** readiness、start、retry、resume、recovery 和 Profile verify 都校验同一 image/Kit/Bundle identity；Kit warning 可记录但不得改变冻结来源。
- [ ] **移除旧链：** 删除 image 内 CLI payload、image CLI lock 和依赖其 SHA 的 verifier/preflight 链；Project Runtime Image 不再因 Kit CLI 版本差异而被要求重建。
- [ ] **发布与离线资产：** 修订 release overlay、offline bundle、preflight、worker entrypoint、Kit verifier、export manifest 及 fixture；重新生成不可变 Kit 和对应证据。
- [ ] **重跑验收：** 完成后重跑本地 L1/L2、真实 Linux/PG、四 Harness L3 export、L4 Host canary、Provider、Pi acceptance 和最终 `v2_only` hard cut。

每个 source correction checkbox 都要留下 source commit、测试命令、Kit/image/Bundle digest 和脱敏日志路径；单元测试通过不能替代对应 Host 或真实 Task 证据。兼容性 warning 的新增测试应覆盖：小版本升级继续、SHA mismatch warning、manifest tamper fail closed、CLI smoke failure fail closed，以及 image 同名 CLI 不被选中。

## 3. 仍然有效的外部门禁

- [ ] 在可访问 PostgreSQL 上重跑 `test_068_migration.py`，并由唯一 migration owner 从实际 current revision 升级到精确 target；另行重跑锁顺序、CAS/generation 和并发测试。
- [ ] 在真实 Linux Host 验证 `renameat2(RENAME_NOREPLACE)`、fsync、目录冲突和崩溃恢复。
- [ ] 准备本轮 Kit-owned release 的四个 CLI payload、Kit/platform/content digest 和 Runtime Bundle；旧 image-owned CLI identity/lock 不得作为新 release evidence，但已核验、不可变且项目工具链未变的 Project Runtime Image 可以复用，并纳入新的 `image_identity + kit_identity + bundle_digest` 组合。
- [ ] Pi、OpenCode、Claude、Codex 各完成一个真实 Task 的 L3 DB-bound Bundle export，并记录 Task、attempt、Adapter、image、Kit、Bundle digest。
- [ ] 完成 Provider 授权、凭据轮换、secret scan、真实 remote Docker inspect 和四 Harness Host canary。
- [ ] 完成真实 Git commit/push/MR、失败/取消/timeout/recovery、session/Skills、usage、archive；OpenCode 验证 server 生命周期，Pi 验证 ACK/顺序/steering/follow-up。
- [ ] 完成 Pi 至少 20 个内部 Task、390×844/768px/桌面浏览器检查，以及可用 Linux/PG/AF_UNIX/scheduler 环境的 skip 重跑。
- [ ] 维护窗口执行独立 hard cut：`PENDING/QUEUED → CANCELLED`，`RUNNING recovery → stop container → FAILED`；V1 historical read 保留，V1 writer/execute/retry/resume/continue 拒绝。

以下输入必须来自同一个 Kit-owned release：Kit archive/manifest/content digest、四个 observed CLI inventory、可复用或新建的 Project Runtime Image identity、Runtime Bundle digest、Adapter digest、Profile generation、Host/daemon identity 和 Task attempt。baseline version/SHA 可不同，运行时不做 semver 分类；应在 acceptance report 中逐 Harness 记录 warning 或 clean result。

## 4. 已完成但必须备注的证据与约束

- `5b9ec15e`、`abb56ae3`、`cda8e6ee` 证明的是旧 image-owned CLI L1/L2 实现（统一制品验证、DB-bound export、identity/evidence/dual-canary/resume）；它们不是 Kit-owned source correction 的发布证据，迁移后必须全部重跑。
- 当前本地回归为 `2960 passed, 61 skipped, 2 deselected, 96 subtests`，明确排除了历史 `test_068_migration.py` 和 scheduler lifecycle；这不等于 L3/L4 通过。
- L1/L2 不等于 production proof；L3 是制品、Host、Profile 和 Bundle 绑定验证，L4 是真实 Task、事件、terminal、usage、Git/MR 和 archive 对账。
- dual-canary 保留 legacy V1 execution path；只有显式 V2 overlay 和完成新 Kit evidence 的 Profile 才能执行 V2。OMP 不进入本轮首发关键路径。
- Task、Profile、image、Kit、Bundle、Adapter bytes、protocol 和 evidence 必须来自同一冻结组合；identity/evidence 不一致时 fail closed，不回退 V1 或混用旧制品。
- Adapter settled 不等于 Task success；command `delivered` 只表示原生 ACK，`outcome_unknown` 不得重放，command history 不得泄露 payload、digest 或 native diagnostics。
- 不在 Git、manifest、日志或验收输出记录秘密；mutable tag、placeholder SHA、未核验或项目工具链已变化的 image，以及未经核验的 Kit manifest，不得冒充 release evidence。
- 旧 image-owned CLI identity/lock 不能作为新 release evidence、Kit identity、compatibility warning 或 L3/L4 release lock；已核验、不可变且项目工具链未变的 Project Runtime Image 可复用，并作为新组合的 `image_identity`。
- `host_mount` break-glass 必须显式选择、逐 Harness 授权并记录来源；不得成为 image/Kit ownership 不清时的自动兜底。

## 5. 当前阻塞、执行顺序与停止条件

当前阻塞是 source correction、外部环境与发布权限，而非已知源码 P0/P1。顺序为：先修合同和 Kit 安装/identity，再修 registry 与全链路校验，随后移除 image CLI lock，重跑 L1/L2，最后依次执行 PG/Linux、release、L3、L4、acceptance 和 hard cut。

发布前的最低核对顺序是：

1. 校验 Kit archive、manifest、content digest、platform 和实际四 CLI inventory。
2. 在目标 Host 安装并验证 root-owned content-addressed Kit，确认实际挂载路径。
3. 运行四个 CLI functionality gate，再比较 baseline 并记录 advisory warning。
4. 绑定 Profile generation、image identity、Kit identity 和 Bundle digest。
5. 执行 fresh、retry、resume、recovery 和 delivery smoke；任何来源改变都重新 verify。

只有第 1–5 步全部完成，才可开始四 Harness L3/L4；任何单 Harness 的 warning 都不能被聚合成全局“兼容通过”，必须按 Harness 保留。

在 Kit-owned 方案、Provider 授权、PostgreSQL/AF_UNIX/Linux/remote Docker、真实测试仓库和不可变 release asset 到位前，不执行 `v2_only`、Pi 默认 migration、生产制品 push 或真实全量切换。外部输入到位后先更新本 tracker 的 checkbox 和脱敏证据路径。

出现 Kit manifest/content/platform 不一致、CLI functionality 失败、identity/evidence 混搭、placeholder/mutable tag、Profile 未在目标 Host 验证、PG/AF_UNIX skip 未重跑、四 Harness 缺真实 Task/MR、secret scan/凭据轮换未完成或 migration owner 不唯一，立即停止。硬切前保持 `dual_canary`，只回到已登记的不可变 image/Kit/Bundle 组合；数据库只 roll-forward，不修改历史 Snapshot、Issue 或证据。
