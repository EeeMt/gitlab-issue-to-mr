# Open-Harness V2 阶段结论与剩余验收计划

**复核日期：** 2026-09-02

> 本文件只保留当前结论、证据边界、剩余退出条件和停止规则。历史 Task 编号、构建日志、镜像 digest、
> generation、测试计数和 Host 运行快照不在正文重复；需要复核时，以 Git history、runtime archive、数据库
> 快照和独立 evidence 为准。

## 1. 当前结论

Open-Harness V2 需要按两个不同里程碑判断，不能把它们混成一个“始终未完成”的大列表：

| 里程碑 | 当前状态 | 准确边界 |
| --- | --- | --- |
| A. Pi + OpenCode `dual_canary` Internal Preview | **已完成** | 公共 V2 合同、Kit/Profile/Bundle composition、Pi/OpenCode 主要执行链路和代表性真实证据已经形成可用 candidate |
| B. 四 Harness、Pi 全局默认、`v2_only` hard cut | **未完成** | R2 适用协议/生命周期矩阵已关闭；仍需正式 benchmark、L5 发布评审和 L6 维护窗口 |

因此，项目不是“没有推进”，而是此前文档把已经完成的实现、历史证据、每轮 readiness 预检和最终 hard-cut
门禁反复列为“剩余工作”，造成了进度失真。

当前应采用以下判断：

- V2 公共地基、中央 execution policy、command plane、Runtime Bundle、Worker Kit identity、四 Harness
  Adapter/fixture，以及 Pi/OpenCode 的主要 Adapter/Bridge 路径已经落地；
- `linux/amd64` 四 Harness candidate 已有不可变 Image/Kit/Profile/Bundle identity 和独立
  [R1 candidate evidence](../evidence/2026-08-31-open-harness-v2-r1-candidate.md)；
- Pi/OpenCode 已有真实成功、失败、timeout/cancel、usage、Session、工具调用、archive 和 delivery 的代表性
  证据，历史上也已覆盖各自声明的三种协议；本轮 [R2 candidate evidence](../evidence/2026-09-01-open-harness-v2-r2-candidate.md)
  又补齐了当前 Bundle 的 OpenCode 两种 endpoint/config 隔离成功链路、Codex Responses 成功链路，以及 Pi 当前 Bundle
  的 `openai_responses` 成功、command delivery/cancel、Worker 缺失后 live rejection/recovery 和 dispatcher crash-recovery unknown outcome；
  Claude 当前 candidate 的 `404 / model_not_found` 失败分类、修正 endpoint 根路径后的 `anthropic_messages` fresh 成功、continue、稳定态取消和 timeout，以及 Codex 当前 `openai_responses` 的 fresh/continue/稳定态取消/timeout 也已归档；R2 已闭合，后续仍只按源码变更影响面补跑，不重新清零全部已冻结证据；
- 当前运行模式仍应保持 `dual_canary`。Profile-local 的 Pi 选择不等于系统全局默认，也不等于
  `v2_only`；
- readiness 是短 TTL 的逐次 canary 预检。过期时必须在下一次执行前重新 verify，但它不是一个永久未完成的
  项目工作包，也不会因此重新打开 R1；
- 未跟踪的测试缓存或文档提交不改变已提交的 runtime source/composition；只有源码、Kit、Image、Bundle、
  Profile 或目标平台发生实质变化时，才按影响面更新 release evidence。

从现在起只保留三个剩余工作包：R3 执行正式 20-task benchmark、R4 完成 L5 发布评审、R5 在维护窗口
执行 L6。R2 已于本轮关闭，执行顺序为 **R3 → R4 → R5**。

## 2. `dual_canary` 的准确边界

`dual_canary` 是 V1/V2 执行合同受控并存，不是同一 Task 双跑、影子流量或自动 A/B：

- 一个 Task/attempt 只执行创建时冻结的一个 contract、Profile、Harness、Runtime Bundle 和制品 identity；
- V1/V2 Profile、Task、Session lineage 和 attempt 不自动升级、降级或跨 generation 复用；
- create、execute/schedule/retry/resume、Scheduler claim/recovery 和 Worker start 都必须经过中央 execution
  policy；
- V2 只向显式选择并通过 verify-runtime 的 Profile/cohort 开放，V1 继续按自己的冻结合同执行；
- 只有 L1–L5 全部通过并获得独立 hard-cut 批准，才可在维护窗口切换 `v2_only`。

普通 canary、故障定位 Task 和修复验证 Task 不自动计入冻结 benchmark。

## 3. 证据层级

| 层级 | 当前状态 | 已证明 | 尚未证明 |
| --- | --- | --- | --- |
| L1 架构/合同 | **通过** | ownership、schema、协议矩阵、identity、roll-forward-only 和 Runbook 边界已冻结 | 后续合同变化仍须回到共享 schema 评审 |
| L2 源码/测试 | **当前 candidate 通过** | V2 公共地基、四 Harness fixture、Pi/OpenCode Adapter、command、catalog、execution policy、options freeze、错误归档/展示和相关回归已形成唯一实现 revision | 后续源码变更须按影响面重跑并更新 evidence |
| L3 不可变 composition | **Internal Preview candidate 通过** | 目标平台的 Image、Kit、Profile、Adapter、Bundle 和数据库 identity 可追溯 | hard-cut 前仍须对最终 candidate 再做一次逐次 readiness 预检 |
| L4 真实 Host/Task | **部分通过** | Pi/OpenCode 的主要成功、失败、Session、usage、terminal、archive、delivery、command/recovery 和协议样本已有代表性证据；当前 candidate 的 8 个适用协议行、Codex/Claude fresh/continue/稳定态取消/timeout、Pi command/recovery 和 OpenCode endpoint/config 隔离已补证 | L4 仍需正式 benchmark cohort、完整 UI/运维验收和发布评审 |
| L5 发布验收 | **未完成** | 场景、统计口径和 UI/运维检查面已经定义 | 正式 20-task、Pi 非劣性、剩余 UI/运维检查和 go/no-go 签署 |
| L6 hard cut | **未执行** | `v2_only`、Pi 默认值和 V1 只读边界已有实现路径 | 尚未进入独立维护窗口执行和验证 |

证据不能跨层替代：单测不能证明 Host 安装，Kit verify 不能证明真实模型与 Git/MR，单个成功 Task 不能证明
协议矩阵或 benchmark，Pi/OpenCode candidate 也不能证明四 Harness hard-cut readiness。
`host_mount` 只允许作为逐 Harness 授权的 break-glass 来源，不得充当 Kit-owned release evidence。

## 4. 与原实施阶段的对照

| 原方案阶段 | 当前状态 | 后续归属 |
| --- | --- | --- |
| Phase 0：协议探针与接口冻结 | **完成** | 真实 Endpoint 的发布 conformance 归入 R2，不再把它算作接口设计未完成 |
| Phase 1：V2 公共地基与 command plane | **完成** | 后续只在相关源码变化时做影响面回归 |
| Phase 2：Pi 默认 Harness | **实现与 dual-canary 完成；发布门禁未过** | 受影响 conformance、幂等/恢复归入 R2；非劣性归入 R3；全局默认切换归入 R5 |
| Phase 3：OpenCode 一级 Harness | **实现与 dual-canary 完成；发布门禁未过** | 受影响 conformance、跨 endpoint/config 隔离归入 R2 |
| Phase 4：Claude/Codex V2 | **源码/fixture 完成；L4 部分完成** | 各自支持协议的当前 candidate 成功证据归入 R2 |
| Phase 5：产品、制品、Canary 与 hard cut | **Internal Preview 完成；发布验收未完成** | benchmark、L5、L6 分别归入 R3、R4、R5 |
| Phase 6：OMP | **未开始且不在本轮范围** | 只在 V2 hard cut 后独立评估 |

当前实现继续遵守既定 ownership：Worker Kit 拥有 Harness CLI payload，Project Runtime Image 拥有项目工具，
Runtime Bundle 拥有 Adapter/Bridge/orchestration bytes；实际执行只认冻结 Snapshot/Bundle/Kit identity，
不得从 image、`PATH`、用户配置或另一 Harness 的成功结果隐式回退。

## 5. 剩余工作与退出条件

### R1 — 冻结 Internal Preview candidate（已完成）

- [x] 唯一实现 revision 已提交，相关 backend/frontend/mock/build 与静态检查已有独立记录；
- [x] 四 Harness 的 Image、Kit、Profile、Adapter、Bundle 和目标平台 identity 可追溯；
- [x] Pi/OpenCode 代表性真实 Task 与归档链路已经建立；
- [x] candidate evidence 已单独保存，不再由本跟踪文件重复抄录逐次数字。

**关闭规则：** 下一轮 canary 前重新 verify readiness 是执行预检，不重新打开 R1。只有 runtime source 或
composition identity 实质变化时，才按影响面补充 evidence。

### R2 — 关闭四 Harness hard-cut conformance（已完成）

按[冻结 schema](../../architecture/open-harness-v2-schemas.md)执行的适用协议矩阵如下：

| Harness | `anthropic_messages` | `openai_responses` | `openai_chat_completions` |
| --- | ---: | ---: | ---: |
| Pi | 是 | 是 | 是 |
| OpenCode | 是 | 是 | 是 |
| Claude | 是 | 否 | 否 |
| Codex | 否 | 是 | 否 |

不得要求 Claude/Codex 执行其未声明的协议，也不得用协议代理、URL 推断、隐式转换或其他 Harness 的成功结果
冒充通过。Pi/OpenCode 已冻结且未受后续变更影响的证据继续有效，只补跑变更实际影响的行。

R2 本轮已完成以下闭环项：

1. **本轮已完成：** 当前 candidate 的 OpenCode Chat、Responses 和 Anthropic 三个成功行均已对账
   config、protocol、usage、唯一 terminal、archive 和 delivery；Provider access failure 仍按原样保留。
2. **本轮已完成：** Codex `openai_responses` 的当前 Profile fresh/continue/稳定态取消/timeout 生命周期已补齐（Tasks `192`–`195`）；Claude
   `anthropic_messages` 的当前 candidate failure Task `186`（`404 / model_not_found`、零 token、无代码交付）和
   endpoint 根路径修正后的 fresh success Task `187` 均已归档。Task `187` 使用 Provider 11 的
   `https://openrouter.ai/api`、Bundle `121`，完成 usage、archive 和 Git delivery；Task `188` 补齐了同一
   session 的 continue，Task `190` 补齐了 attempt 初始化后的稳定态取消，Task `191` 补齐了全局 timeout；Task
   `189` 的创建前 early-cancel race 单独保留，不能作为 Harness cancellation conformance。适用协议矩阵的完整
   当前-candidate success/failure 与生命周期逐行收口已完成。
3. **本轮已完成：** 当前 Bundle 已有 Pi 正常运行和控制端点启动；幂等 replay、closed gate 和 Scheduler
   recovery 的聚焦套件已通过；Task `181` 完成了 queued command 在 Worker 缺失后的
   `control_gate_closed` live rejection/recovery，Task `182` 完成了实际 command delivery 与取消收敛，Task
   `184` 完成了持久化 `dispatching` 命令在 dispatcher crash/recovery 后的 `outcome_unknown` 收敛，Task `185`
   完成了当前 Bundle Pi `openai_responses` 的真实成功链路，Task `197` 完成了当前 Bundle Pi
   `anthropic_messages` 的真实成功链路。
4. **本轮已完成：** 不同 endpoint/config 的真实 OpenCode Task 已证明 task-private namespace、endpoint
   fingerprint 和 task-local config 不会未声明串线；详见独立 evidence 文件。
5. **本轮已执行受影响聚焦回归：** Linux/PostgreSQL 的 Scheduler、command、attempt、terminal、archive
   和 recovery 相关 suite 已通过；源码或 composition 后续再变更时，只按实际影响面重跑，不清零既有 green evidence。

**退出条件：** 已满足。所有适用协议行和上述闭环项均可追溯，无隐式回退、跨 Task 污染、重复 terminal
或 P0/P1；失败样本保留原样，没有事后追认为成功。

### R3 — 执行正式 20-task benchmark（进行中）

- 严格使用 [V2 schema §11](../../architecture/open-harness-v2-schemas.md#11-20-%E4%B8%AA-benchmark-%E4%BB%BB%E5%8A%A1%E4%B8%8E%E7%BB%9F%E8%AE%A1%E6%96%B9%E6%B3%95)
  冻结的 20 个多样化场景、成功标准、可比 Endpoint/model 和统计方法；
- [x] 开始前冻结 candidate、Provider/model、协议映射、人工验收口径和独立 Issue/lineage 隔离策略；详见
  [R3 benchmark cohort evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 01–03 的 Pi/OpenCode 正式配对：场景 02 的 OpenCode 首次停滞取消（Task `203`）保留为失败
  证据，独立 fresh retry（Task `204`）成功；场景 03 的 `freeform/fresh`（Task `205`/`206`）也已成功；当前
  登记册已更新；
- [x] 已完成场景 04 `execute/fresh` 工具成功配对（Task `207`/`208`）：两边均有成功只读 shell 检查、完整
  tool start/complete 配对和 marker delivery；无害路径探测错误保留在 TaskLog；当前登记册已更新，场景
  已同步更新；
- [x] 已完成场景 05 的严格工具失败配对：Pi Task `228` / Issue `48` 与修复后 OpenCode Task `231` / Issue
  `50` 均产生 standalone `exit 7` 的 canonical `tool.completed(error=true)`，随后继续完成 marker delivery；
  初次掩盖退出样本 `226`/`227` 和暴露 `exit_code=7,error=false` 的 OpenCode 样本 `229` 均保留，且已用
  `0b4cb177` 修复两条 translator 路径；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 06 的 post-fix failure→delivery 配对（Pi Task `223` / Issue `44`，OpenCode retry Task
  `225` / Issue `45`）：两边都记录了同一测试的初始失败与成功重跑，并最终只交付 `r3-s06.py`、
  `r3-s06_test.py`；OpenCode 首轮 Task `224` 的真实 `permission.asked` / `sandbox_error` 失败保留。由于
  `d26971ec`、`796fe051` 先后影响交付清理与 OpenCode Task-local scratch 权限，以上是按源码影响面追加的
  post-fix candidate evidence，不静默替换原始 candidate 记录；当时 R3 登记册剩余场景 07–20；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)。
- [x] 已完成场景 07 的无改动配对：Pi Task `232` / Issue `51` 与 OpenCode Task `233` / Issue `52` 均为
  `execute` + `require_changes=false`，只读检查后以 canonical `run.completed(success=true)` 收敛，
  delivery/finalization 均为 `0/0` 且远端 workspace clean；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)。
- [x] 已完成场景 08 的正式可比 fresh→continue 配对：Pi Task `238` → `239` / Issue `55` 与 OpenCode
  Task `236` → `237` / Issue `54` 均使用同一 Issue/lineage、`require_changes=true` 和冻结 Provider，
  input/output session 可追溯，最终都只交付 seed + continuation 文件；早期 Pi `234` → `235` 的
  `require_changes` 配置差异作为保留诊断样本记录；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)。
- [x] 已完成场景 09 的 Pi/OpenCode 稳定态取消配对：Pi Task `240` 与外部 fixture 恢复后追加的 OpenCode
  Task `275` 均在 `tool.started(sleep 120)` 后由 UI 取消，canonical
  `harness.failed(cancelled)` → `worker.finalization(exit_code=143)` → `run.failed(cancelled)`、archive
  和 container 清理均成立；OpenCode Task `241`→`242`→`243` 及短 prompt Task `244` 的首工具前
  `protocol_error` 失败仍保留；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)。
- [x] 已完成场景 10 的 Pi/OpenCode timeout 配对：Pi Task `245` / Issue `59` 与 OpenCode Task `246` /
  Issue `60` 均在 `tool.started(sleep 180)` 后由临时 `60s` runner timeout 产生
  `harness.failed(timeout)` → `worker.finalization(exit_code=143)` → `run.failed(timeout)`，archive 和
  container 清理成立；随后将全局 `task_timeout` 恢复为 `1800s` 并确认队列为空；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)。
- [x] 已完成场景 11 的 Pi compaction/recovery 证据：正式 Task `251` 产生 5 个 `context.compacted` 后以
  唯一 `run.failed` 收敛，同一 Issue 的 Task `252` 完成 post-compaction marker delivery；OpenCode Task
  `253` 与恢复后追加的 `276` 分别产生 41/41、37/37 tool 和 4、3 次 retry，但都没有 compaction，最终
  为 `engine_error: unknown certificate verification error`。随后冻结 Provider 7 的正式重跑 `#293`（50 个
  2,000 行 direct chunk，cached `316,034`）与 `#295`（50 个 8,000 行 direct chunk）均成功 delivery，
  但 raw/canonical/Host 仍没有结构化 `context.compacted`；`#294` 实际为 `sed | wc -l` 的 count-only
  探针。TLS error 本轮未再复现，当时场景 11 登记为 `blocked_external_fixture`，不把 Pi 半边追认为完整
  通过。2026-09-02 以已有 alternate Provider `12`、Bundle
  `137` 追加 `#290/#291/#292` 诊断；其中 `#292` 在真实 `README.md` 上完成 40 次有效读取，canonical
  `46/46` tool、seq `1–370`，cached input `68,894`，但 raw/canonical/Host 仍为 0 个
  `context.compacted`，不改变冻结 Provider `7` 的外部 fixture blocker。随后 `#313` 沿用过大的既有
  continuation lineage，在 `1800s` runner timeout 收敛且没有 `session.idle`；`#314` 在 Bundle `139`
  上完成 fresh legacy summarize probe，产生 `context.compacted=2`；`#315` 完成 12,000 行长上下文、
  37/37 tool，raw `session.compacted=1`、canonical `context.compacted=3`，其后为唯一
  `run.completed`。因此场景 11 现在登记为 `pass`；#313 的 timeout 和前述无 compaction 样本均保留为
  历史边界证据，V2 native compact `503` 保留为固定 OpenCode `1.18.19` 的上游能力边界；详见
  [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 场景 11 的 native OpenCode compact route 探针已完成但未通过：源码提交 `a915fb70` 将 Task-local
  session marker 调整为 Task 进程可读，Profile 4 generation `53` 生成 Bundle `138`；Provider `7` 的
  `#298`（旧 Bundle `137`）与 `#300`（新 Bundle `138`）均真实调用 OpenCode `1.18.19` 的
  `POST /api/session/{sessionID}/compact` 并返回 `503`，canonical/raw 均为 0 个 compaction event。
  `#300` 的 fixture 命令还因遗漏输出重定向退出 `2`，不能作为有效长上下文样本；Provider `3` 的 `#299`
  与 Provider `4` 的 `#301` 在进入 Harness 前均为真实 `rate_limited`。这些结果排除了 marker 权限障碍，
  但未提供 OpenCode compaction event/fixture；V2 native compact route 仍受固定 OpenCode `1.18.19`
  的上游能力边界限制，不再
  叠加 alternate-provider 探针。随后在同一冻结 Provider `7`、Bundle `138` 上完成最后一轮 idle-window
  诊断：`#302` 因 frozen Worker image 没有 `jq` 导致 watcher 超时后取消；`#303` 使用 grep-only watcher，
  但因 `session.idle with active tool parts` 以 `protocol_error` 失败；`#304` 使用修正后的最小 fixture
  probe 仍以同一 `protocol_error` 失败。随后 `#305/#306` 的 clean-idle Task-local watcher、`#307` 的
  空白容忍 watcher 和 `#308` 的远端 Host-side watcher 均未在容器清理前形成可追踪的 compact HTTP 状态；
  四个 Task 都只留下一个 raw `session.idle` 和正常 terminal，没有 canonical/raw compaction event；这些
  结果作为 V2 native route 的历史边界证据保留。随后在同一 Issue `#92`、Provider `7`、Profile `4`、Bundle `138`
  上追加真实 `#309`（`plan/continue`，6/6 tool）和 `#310`（`freeform/continue`，82/82 tool，80 次有效
  direct file read），两者均 completed 但 raw/canonical 仍没有 compaction；`#310` 沿用 `#309` 的 session
  lineage。2026-09-02 对固定 Kit 中 OpenCode `1.18.19` 的 exact-tag
  compaction source 做了只读核对：该版本只有 automatic/overflow compaction processing，没有 V2
  manual compaction producer；官方上游 issue [#40614](https://github.com/anomalyco/opencode/issues/40614)
  记录 `SessionV2.compact` 当前为 `OperationUnavailableError` 并由 Server 映射为 `503`。因此
  `#298/#300` 的 `503` 是固定上游能力边界，不是 Codify adapter 的 event-order 缺陷；在获得支持
  manual compaction 的新 Kit/固定 build 或可验证 automatic-compaction fixture 前，不再叠加同类 route
  probe，也不放宽 `session.idle` active-tool 的 fail-closed 规则；详见
  [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已执行场景 12 的两轮正式 Pi/OpenCode retry probe：`254/255` 与 `256/257` 均成功完成并交付，
  但四个任务都没有 `provider.retry`；在 readiness generation `62` 上追加的当前 Provider 7 formal
  acceptance re-probe `#332/#333` 也分别以 60/60、51/51 tool 成功完成、没有 `provider.retry` 或
  `rate_limited`；`250/251` 以及后续 Provider 9 真实诊断 `#317` 的 `rate_limited` 事件作为关联诊断
  保留，不重复计入 formal 配对，因此场景 12 登记为 `not_triggered`；详见
  [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [ ] 场景 13 的认证失败仍为 `blocked_external_fixture`：只读复核 Provider `3–12` 均 enabled，开发环境
  没有专用 401 fixture；#296/#310 的无凭据请求是 OpenCode Server Basic Auth，不是 Provider 401；历史
  `#150/#151` 的 `authentication_error` 实为 `404` HTML，不能计入；后续 #316 是 certificate
  `engine_error`，#317 是 Provider 9 的 `429/rate_limited`，#319 是 Provider 6 的 `429/rate_limited`，
  均不是 401；未读取或修改 Provider secret，
  不伪造认证错误；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 14 的 invalid-session 与 network interruption 子场景：OpenCode `#281 / Issue #84`
  的真实不存在 Session 以 `engine_error` 收敛，当前 Pi `#289 / Issue #87` 的真实 bogus lineage 以
  Adapter-side `protocol_error: Pi parent session is not available` fail-closed；两边均有唯一 terminal、
  archive、无 output session 和 Worker 清理证据。随后在 `192.168.50.129` 用已有 Provider 7 / Profile 4
  做了 Pi `#320/#321` 与 OpenCode `#322/#323` 的 bridge 断网探索，以及 #330/#331 的过期 readiness
  namespace egress probe；前者恢复后可继续或安全收敛，后者产生了真实 `engine_error` retry 但不计入正式
  canary。Profile 4 readiness generation `64`（`2026-09-02 04:08:33.825663`）有效窗口内，Pi
  `#334` 与 OpenCode `#335` 在首次工具后施加一次 443 egress 阻断，分别产生 3/5 次 `engine_error`
  `provider.retry`，并以预期的 `run.failed(engine_error)` / 恢复后的 `run.completed` 唯一终态收敛；
  network interruption 子分支现已闭合，详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成 Pi 原生 session persistence 影响面修复与真实控制：修复 `e33df7e6` 通过 63 个 Pi
  focused tests；Profile 4 generation `52` / Bundle `136` 下 `#287 → #288 / Issue #86` 完成
  fresh→continue，DB output 与 Host JSONL header 一致，child header 含原生 `parentSession`；修复前
  的 #285 ID capture mismatch 与 #286 fail-closed 中间证据保留；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 15 的 longest-context 正式重跑：初次 `#271/#272` 保留为未达 50-call 指令的 probe，
  独立长输入重跑 `#273 / Issue #81`（OpenCode）与 `#274 / Issue #80`（Pi）分别完成 21/21、24/24
  tool，cached input `20,822` / `18,006`，唯一 `run.completed`、0/0 delivery；两边没有
  `context.compacted`，按 `not_triggered` 记录该边界，不伪造压缩事件；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 16 多文件重构：Pi `#258 / Issue #69` 与 OpenCode `#259 / Issue #70` 均完成
  `r3_s16.py` + `r3_s16_test.py` 的测试、commit、delivery；模型先 commit 导致公共 finalization diff 为
  `0/0`，canonical delivery/finalization SHA 已登记；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 17 单文件 bug fix：Pi `#262 → #265 / Issue #73`，OpenCode `#263/#264 → #268 /
  Issue #74`；OpenCode 两次真实 `session.idle with active tool parts` 失败保留，最终 recovery 完成
  单文件修复、测试和 delivery；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 18 纯分析：Pi `#260 / Issue #71` 与 OpenCode `#261 / Issue #72` 均只读完成，
  `commit_sha=null`、delivery/finalization `0/0`、workspace clean；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [x] 已完成场景 19 的独立 failure→public delivery cohort：Pi `#277 → #279 / Issue #82`、OpenCode
  `#278 → #280 / Issue #83` 均在同一 Issue/lineage 中保留首轮 failure，再由 fresh recovery 任务完成
  唯一 marker 文件的公共 commit、MR、canonical terminal、archive 和 Worker 清理；`#277` 的 delivery
  failure 与 `#278` 的稳定态取消均保留，不与场景 11、17、20 重复计数；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)。
- [x] 已完成场景 20 高 token 生成：Pi `#266 / Issue #75` 成功；OpenCode `#267/#269 / Issue #76`
  的 protocol/delivery failures 保留，独立 `#270 / Issue #77` 完成三个 80 行文件、报告和公共 delivery，
  finalization diff `240/0`；详见 [R3 benchmark evidence](../evidence/2026-09-01-open-harness-v2-r3-benchmark.md)；
- [ ] 当前 R3 未闭合项包括：场景 12 的 formal `provider.retry` 仍为 `not_triggered`、场景 13 的真实 401 fixture；
  本轮用已有 Provider 11 追加的真实
  OpenCode 任务 `#316` 只得到 `engine_error: unknown certificate verification error`，没有 Provider HTTP 401，
  不能替代 fixture；随后用已有 Provider 9 追加的真实 OpenCode `#317` 由 raw
  `APIError.data.statusCode=429` 证实为 `rate_limited`，也不能替代认证 fixture；随后在 Profile 4
  generation `57`、Provider 7、Pi 上追加的真实控制任务 `#318` 成功完成但没有 `provider.retry`，也不
  能替代认证 fixture；历史 `#150/#151` 的旧
  `authentication_error` 由 raw `404` HTML 证实为无效样本，当前 `ab869c67` 的 Pi 回归测试已防止裸词
  `authentication` 再次误分类；Provider 7 的 TLS error 本轮未再复现，
  `#313` 的过大 continuation 以 `1800s` timeout 保留为失败证据。`#314/#315` 在新生成的 Bundle `139`
  上通过默认关闭、exact-marker 的 legacy `/session/:sessionID/summarize` Bridge hook：其中 `#315`
  是 12,000 行长上下文、37/37 tool，raw `session.compacted=1`、canonical `context.compacted=3`，
  其后为唯一 `run.completed`；因此场景 11 已闭合。V2 `/api/session/:sessionID/compact` 的 `503`
  仍是固定 OpenCode `1.18.19` 的上游能力边界，未追认为 adapter 缺陷；场景 13 仍因没有真实
  Provider 401 fixture 保持 blocker；场景 14 的 invalid-session 与 network interruption 子场景已闭合，
  #320–#331 的 bridge/过期 readiness probe 作为历史边界证据保留，#334/#335 的有效 generation `64`
  canary 不改变 frozen pair 分母；当前冻结 cohort 已登记 19/20 个场景的 formal Pi/OpenCode pair，
  场景级 rollup 为 18 个 full pass、0 个 partial、1 个 `not_triggered`、1 个
  `blocked_external_fixture`；在这些未闭合项完成前不关闭 R3，也不进入 R4；
- [ ] 在冻结 cohort 上分别执行 Pi 与 OpenCode 的 20 个同场景样本（当前已完成 `#1–12`、`#14–20` 的
  formal pair；场景 13 尚无可接受 pair；需要 fresh/continue 或 failure→delivery 的场景按一个场景登记多个 Task）；
- 每个样本记录验收结论、failure taxonomy、耗时、token、工具调用、archive 和 delivery；修复后可重跑，
  但不得删除失败样本或把探索性 canary 追认成 benchmark；
- [现有 benchmark shell](../../../scripts/harness-probes/v2/benchmark.sh) 只重复生命周期诊断 prompt，
  不能替代 §11 的正式验收 cohort；
- Pi 与当前较优兼容 Harness 做同任务对比：成功率下降不超过 10 个百分点，中位耗时和 Token 不得同时
  恶化超过 25%。

**退出条件：** 不少于 20 个冻结样本完整可追溯，统计口径一致，Pi 质量和性能门槛同时通过。

### R4 — 完成 UI、运维与发布评审

已完成的部分不再重复列为待办：

- [x] 手机、平板和桌面基础响应式 spot-check；
- [x] 关键任务信息可见性、横向溢出和主要触控尺寸基线；
- [x] 失败详情、Raw Logs、原始 console 与结构化归档的基本展示边界。

剩余检查：

1. 完成移动端键盘/安全区、长文本换行、断线重连和 command history 的真实交互验收；
2. 审阅四 Harness 的 success/failure taxonomy、protocol error、command latency、usage、terminal、
   archive 和 delivery 指标；
3. 在最终 composition 上完成 secret scan、Provider/GitLab 授权与凭据轮换核对、release note、旧 Kit
   退役计划和 P0/P1 清零；
4. 形成独立 hard-cut go/no-go 评审记录并签署。

**退出条件：** L5 检查全部通过，发布评审明确批准进入 L6。

### R5 — 在独立维护窗口执行 L6

R2–R4 未全部通过前不安排 R5。获得单独批准后，按
[dual-canary 与生产验收 Runbook](../../runbooks/multi-harness-rollout.md)：

1. 排空在途任务、备份数据库并冻结 V1 只读边界；
2. 切换新建 Profile 的 Pi 全局默认值和 `HARNESS_EXECUTION_MODE=v2_only`；
3. 执行四 Harness smoke、Scheduler recovery、command plane、统计和历史只读检查；
4. 失败时保持维护状态并 roll forward，不启动旧 V1 应用回滚。

**退出条件：** L6 smoke 与运行态核对全部通过，且 hard-cut 结果形成独立 evidence。

## 6. 明确不进入本轮的工作

- 不增加撤销、denylist、任务迁移、紧急回退状态或新的 schema；没有真实需求时不建设过渡机制；
- `linux/arm64` 只在目标 Host 清单实际出现该架构时增加，不为假设平台提前扩张矩阵；
- OMP 保持独立实验，只有 V2 hard cut 后才用同一 benchmark 评估；
- 不重复消耗已知受限 Provider，也不使用协议不兼容的 Provider 冒充 Claude/Codex 成功。

## 7. 停止条件

出现以下任一情况，立即停止当前层级并保留证据：

- 实际执行 bytes 与冻结的 Image、Kit、Bundle、Adapter、Profile、Host platform 或 attempt identity 不一致；
- 使用 mutable tag、placeholder digest、未验证 Kit、过期 readiness、`host_mount` 或旧 image CLI lock
  冒充 release evidence；
- 出现协议推断/转换/回退、超出冻结矩阵的组合，或适用协议缺少真实 Endpoint conformance；
- V1/V2 cohort、task-private config/namespace、command 顺序/幂等、concurrency 或 recovery 出现隔离失败；
- 任一 hard-cut Harness 缺少当前 candidate 的适用成功证据、唯一 terminal、usage、archive 或 delivery；
- 存在 P0/P1，或正式 benchmark、Pi 非劣性、L5 评审尚未通过却准备进入 L6。

单个 Harness 的 functionality gate 失败只能把该 Harness 标为 unavailable，不能借用其他 Harness 的成功
结果。数据库继续保持 roll-forward-only，不得改写历史 Snapshot、Issue、attempt、archive 或验收证据。
