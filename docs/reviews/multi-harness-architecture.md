# 多 Harness 引擎架构调研报告:抽象与优雅度评估

- **日期**: 2026-08-07
- **依据**: 本轮深度 review 的代码实证 + 全部阶段规格文档(roadmap / Phase 0-4 / 设计文档 / 两份 contract)
- **范围**: Claude(Phase 1 无回归核心)+ Codex(Phase 2 生产候选)+ 未来 OpenCode(Phase 4 条件候选)

---

## 0. 一句话抽象

Codify 本质上是一个**引擎无关的代码交付平台**。在这种架构里:

> **Harness = 前端编译器**(consumes prompt + 冻结配置,产出 canonical IR)
> **Canonical Event v1 = 中间表示(IR)**
> **共享运行时 = 后端**(scheduler / delivery / workspace / MR / analytics)

**整个系统的优雅度 = IR 捕获质量 × 共享层纯度。** 所有具体问题都能归约到"IR 泄漏"或"纯度破坏"两类。

---

## 1. 规格已经写得很好的部分(优雅的基线)

| 机制 | 评估 |
|---|---|
| **13 条不可变决策**(roadmap §2) | 决策 5/6/7/8/10/12 尤其关键:canonical 唯一协议、幂等回放、session 隔离、Skills 中立、fail-closed、版本不可变 |
| **Canonical Event writer 不变量** | flock + seq 从流推导 + 单终态 + 终态必须最后——最优雅的单点,把"审计可回放"做成了强制 |
| **Runtime Bundle / Kit 双层版本** | Bundle manifest 是执行真相,Kit 只声明兼容范围;内容寻址 + 全链 digest 校验 |
| **能力策略** | system upper bound + profile 收紧,只紧不松(尽管存在真相分歧 bug) |
| **fixture 金样测试** | 真实探针 → 清洗 → 离线回放。最强的质量机制,唯一真正"钉死"协议演进的方式 |
| **Phase 4 纯度审计** | "加 opencode 不得改 projector/runner/TaskForm 业务分支"——纯度变成验收标准 |

**结论:目标架构本身优雅。问题在实现与目标的偏差,以及一个被规格忽略的架构决策(流式/终态)。**

---

## 2. 四个抽象视角

### 视角 A:插件契约(harness contract 作为接口)

契约定义 11 个操作(metadata/verify/detect/prepare/build/materialize/stream/normalize/terminate/run_text/run)。

**优雅的**:接口覆盖生命周期;capability 是类型化值;未知 capability 忽略。

**不优雅的**:
- **契约操作未被行使**:`terminate` 两个 adapter 都有实现(一个 TERM、一个 no-op),但 **runner 从不调用**。没人调用的契约操作,各写一份没人执行的语义 → 必然漂移。
- **声明未强制**:`cli_version_range` 写在 manifest,但**无任何代码读取**。claude 硬编码下限、codex 完全不查。

**抽象教训:契约每一项要么被公共层行使、要么移除;每一项声明要么被强制执行、要么删除。**

### 视角 B:状态与身份

**session/thread/conversation**:各引擎术语不同,外部收敛为 opaque id + namespace。方向正确。

**namespace 收窄为 3 输入并文档化(2026-08-08)**:契约原列 5 个输入(harness + endpoint fingerprint + 认证域 + 工作区身份 + state major),实现只有 3 个。经评估后确认 3 输入是正确形态并已把契约文档对齐:
- **workspace identity 冗余**:由 `issue_id` 隐含(会话行已按 issue 作用域),再哈希进 namespace 是重复。
- **authentication domain 若按凭据实例定义则有害**:凭据轮换会清空会话;真正该防的"跨认证方式续接"已由 endpoint fingerprint 的非敏感 auth-scheme 字段(provider_kind/wire_protocol/driver)覆盖。
- 见 `docs/architecture/worker-harness-contract-v1.md`。

**抽象教训:身份作用域要么完整,要么显式收窄并写理由。**

### 视角 C:数据流与每引擎状态(最深根因)

> **逐行子进程 translator → 跨行状态落到侧文件 → 终态决策碎片化。**

- codex translator 被迫积累 **5 个侧文件**(thread-id、last-text、retry-count、model-resolved、terminal-state),每个都是"子进程架构"的补偿
- 终态"最后 turn 为准"是 **EOF 才能回答的问题**,被拆到 translator(持久化)+ codex.sh(补发)+ codex-run.sh(定退出码)三处
- claude 靠 `.real-session-id` 侧文件,同样的病,轻症

**抽象教训:状态应该住在观察它的那个进程里。终态决策发生在 EOF,而只有流式进程能看到 EOF。所以 translator 必须是单个流式进程,读 stdin 到 EOF,状态全在内存,终态在 EOF 单点发出。** 这是引擎中立的正确形态,任何有多阶段运行的引擎(opencode 很可能)都会撞上同一堵墙。

### 视角 D:演进与兼容

**做得好**:roadmap 要求向后兼容的 v1.x、三套 fixtures 证明通用需求、真实探针矩阵。

**风险点**:所有引擎特有扩展都靠 `engine_fields` 逃生舱。该舱位必须**只展示、不决策**——一旦公共逻辑开始读 engine_fields 做分支,纯度就破。

---

## 3. 偏离优雅的根因清单

| # | 根因 | 当前形态 | 抽象归类 |
|---|---|---|---|
| 1 | **逐行子进程 translator** | codex 5 侧文件 + 终态碎片;claude 1 侧文件 | 状态住错地方(视角 C) |
| 2 | **能力真相三处无交叉校验** | registry `SYSTEM_CAPABILITIES`(静态)≠ manifest(per-bundle)≠ adapter `detect_capabilities`;run_text/task_skills 分歧未被发现 | 单一事实源被破坏(视角 A) |
| 3 | **sanitizer 双份且 codex 弱** | claude 有 cookie/path/tool-id/隐藏推理清洗;codex 缺 | 敏感内容模式是引擎无关的,却在每引擎重写 |
| 4 | **失败分类器双份** | 两 translator 各有 `_failure_kind`,关键字集重叠 | 同上,引擎无关逻辑重复 |
| 5 | **契约死操作/空声明** | terminate 无人调用;cli_version_range 无强制 | 契约未被行使(视角 A) |
| 6 | **展示层引擎残留** | TaskMetadataPanel 按 harness key 分支(展示可接受);bootstrap 预创建 claude.jsonl(轻度杂质) | 展示/业务边界(视角 B) |
| 7 | **console 显示不对称** | claude 富显示,codex 全无 | "显示住哪"未决策(视角 C/D) |

---

## 4. 未来 harness(opencode)的含义

Phase 4 文档已把门槛写得很对:六项准入、hermetic 配置证明、纯度审计、真实探针。但若上面 7 个根因不先清理,每加一个引擎都要付同样的隐形成本:

- 一份新的逐行 translator + 新的侧文件组合
- 一份新的 sanitizer(照 claude 抄)
- 一份新的失败分类器
- 一个新的 capability 真相分歧点
- 一次"terminate 又没被调用"的复制

**opencode 的真正价值不是"第三个引擎",而是它作为纯度测试**:如果加它时只需要 adapter + fixtures + registry 条目 + manifest,四件事,零公共层改动——架构就是优雅的。当前答案接近"是",但带 7 个减号。

---

## 5. 统一优先级建议

**P1(让"加引擎"变便宜——为 opencode 铺路):**
1. **translator 流式化**:codex 先做(正确性所需),claude 单独提交跟进(状态进内存,删侧文件,终态时序不变)。消灭整个侧文件类别 + 终态碎片。
2. **能力真相交叉校验**:bundle 构建时用 registry 校验 manifest capabilities,不一致即构建失败。
3. **共享 sanitizer 模块**:抽取 claude 的完整模式集为共享实现,codex 换用(顺带修掉 codex 的安全缺口)。

**P2(契约与身份完备):**
4. **契约收口**:terminate 要么由 runner 真正行使(TERM→grace→KILL),要么移出契约。
5. **cli_version_range 从 manifest 强制** —— **保持不强制,改为 advisory 告警(2026-08-08)**:新增 `harness/version_range.py` 评估声明范围,两个 adapter 的 `verify_runtime` 在 CLI 版本超出范围时打印 WARNING(advisory,不阻断);注释已写明。仍是设计上不强制,但运行时可见。
6. ~~session namespace 补齐 5 输入或显式收窄~~ —— **已澄清(2026-08-08)**:选"显式收窄 + 文档对齐",契约已改为 3 输入并写明理由,代码注释同步。见 §视角 B。

**P3(展示与打磨):**
7. **console 显示决策**:给 codex 补富显示,或明确"UI 时间线即显示、console 走 generic renderer"。
8. **纯度审计 CI 化**:`rg "claude|codex|opencode"` 作为门禁,按合法(registry/展示名)vs 非法(业务分支)分类。

---

## 6. 结论

- **目标架构优雅**:IR 协议 + 插件契约 + 双层版本 + fixture 金样,是教科书级的"引擎无关执行平台"设计。
- **最大隐患是根因 #1(流式/终态)**:它不在 13 条不可变决策里,却被 codex 的多 turn 语义逼出来。这是规格盲区,不是实现失误。
- **优雅的真正度量 = opencode 接入成本**。把它当作"纯度验收",而不是第三个功能。

---

## 7. P1 执行进展

**P1 全部完成(2026-08-08)**,四项均已独立提交 + 开发环境真实验证:

| 项 | 提交 | dev 验证 |
|---|---|---|
| P1.1a codex translator 流式化 | `872f864b` | Task 548(codex)replay 干净、单一终态 |
| P1.1b claude translator 流式化 | `a1a95617` | Task 549(claude)replay 干净、真实 session 保留 |
| P1.2 能力真相交叉校验 | `d28c2b76` | Task 550 能力校验未阻断构建 |
| P1.3 共享 sanitizer 模块 | `d28c2b76` | Task 550 raw 归档已清洗 |

### P1.1a codex translator 流式化 —— ✅ 完成 + dev 验证

- `codex_events.py`:改为单个流式进程(读 stdin 到 EOF),全部跨行状态进内存 `_STATE`(thread-id / retry-count / model-resolved / last-assistant-text / 终态),EOF 单点发 harness 终态。**7 个侧文件全部删除**。
- `codex-run.sh`:整流喂单个 translator 进程;退出码按 `harness-result.json` 的 status 判定(completed→0 / failed→1 / 无终态→codex 退出码)。
- `codex.sh`:删除 `codex_adapter_emit_terminal`(终态决策收敛到 translator EOF 单点)。
- 测试:29 条 codex adapter 全过(含新 `test_codex_turn_failed_after_completion_is_the_terminal`,直接断言"后到的 turn.failed 覆盖先到的完成");backend 全量 **2296 passed**。
- **dev 验证(192.168.50.129,Task 548)**:真实 codex 任务完成,canonical 流 `run.started → … → usage.final → harness.completed(EOF) → delivery.* → worker.finalization → run.completed`,replay 无缺口、单一终态,真实 session_id 保留,commit 推送成功。

### P1.1b claude translator 流式化 —— ✅ 完成 + dev 验证(2026-08-08)

- `claude_events.py`:改为单个流式进程(读 stdin 到 EOF),真实 session id 进内存 `_REAL_SESSION_ID`,**删除 `.real-session-id` 侧文件**。终态时序不变(仍内联于 result record),纯状态管理重构。
- `ci-claude.sh`:translator 由每行子进程改为**单个流式进程**(FIFO + 常驻 fd 9 喂入,EOF 由关闭 fd 9 触发);显示循环/进程组/watchdog 完全不动;watchdog 开头丢弃继承的 fd 9 使 translator 及时拿到 EOF;cleanup 兜底 kill translator。
- 测试:新增 `test_ci_claude_feeds_streaming_translator`(真实 ci-claude.sh + fake claude + translator env,验证 canonical 事件 + raw 掩码 + 真实 session 保留);claude adapter 测试整流喂入;backend 全量 **2297 passed**。
- **dev 验证(192.168.50.129,Task 549)**:真实 claude 任务完成,canonical 流 `run.started → … → harness.completed → delivery.* → run.completed`,replay 无缺口、单一终态,真实 session `3bdceaed-…` 保留(raw 掩码),usage 有效。

### P1.2 能力真相交叉校验 —— ✅ 完成(2026-08-08)

- 新增 `harness_registry.validate_adapter_capabilities()`:adapter manifest 声明的能力**不得超出** `SYSTEM_CAPABILITIES` 系统上界(如 codex `run_text`/`max_turns` 声明 True 即构建失败);under-declare(收紧)与未知能力合法。
- 接入 `build_runtime_bundle`(打包即校验)与 `validate_runtime_bundle_manifest`(冻结校验)。
- 测试:registry 拒绝/放行用例 + 真实 manifest 守卫测试(未来越界即失败)。

### P1.3 共享 sanitizer 模块 —— ✅ 完成(2026-08-08)

- 新增 `deploy/worker-entrypoint/harness/adapters/sanitize.py`:claude 的完整清洗模式集(URL/token/Bearer/cookie/`/Users` `/home`/probe 路径/tool-id/UUID)+ `redact_hidden_reasoning` + `clean_message`。
- claude/codex translator 均改用共享模块;**修掉 codex 的安全缺口**(此前缺 cookie、path、tool-id 清洗)。两引擎原始流清洗一致。
- 测试:新增 `test_codex_sanitize_covers_shared_patterns`;全部 translator/fixture 测试通过,无 fixture 回归。
