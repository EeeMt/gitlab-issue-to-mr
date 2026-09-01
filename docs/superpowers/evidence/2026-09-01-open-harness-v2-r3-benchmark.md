# Open-Harness V2 R3 Benchmark Cohort

**冻结日期：** 2026-09-01  
**状态：** cohort 已冻结，真实 Task 执行进行中；未完成前不进入 R4/R5。

本文件是正式 benchmark 的登记册。R1/R2 的 canary、故障定位和修复验证 Task 不回填到这里。每一
个场景都以相同的语义 prompt、项目主分支和 Provider 参数分别运行 Pi 与 OpenCode；因此 20 个场景
对应一组配对样本，实际至少 40 个 Codify Task 记录。需要 fresh/continue 或 failure→delivery 两个
生命周期动作的场景，会在同一 Harness 的场景栏登记多个 Task，但仍只算一个场景样本。

## Frozen runtime and comparison

- Host：`192.168.50.129`，平台 `linux/amd64`，执行模式 `dual_canary`。
- Profile：`4 / v2-canary-0.6.11-four-harness`。
- Worker image：
  `127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`。
- Pi Bundle：`123`，digest
  `9d7ae9cc1aa957af26dcf98a2ded6d7c8738529ab8c0693178d9303e10b84c9d`，Pi `0.84.2`，Adapter `2.0.0`。
  这是本轮 readiness re-verify 后由当前 Profile 4 生成的 candidate；它与 Bundle `122` 的运行时、Kit、
  Image、Adapter 和文件 manifest 相同，仅 verification generation/time 与派生 bundle digest 更新。
- OpenCode Bundle：`124`，digest
  `5886b3026ecc8c483c85c0affb81b21a4e397f5c75ea414649c74b5b63233e51`，OpenCode `1.18.19`，Adapter `2.0.0`。
  这是本轮 readiness re-verify 后由当前 Profile 4 生成的 candidate；它与 Bundle `119` 的运行时、Kit、
  Image、Adapter 和文件 manifest 相同，仅 verification generation/time 与派生 bundle digest 更新。
- 可比成功基准 Provider：`7 / openrouter-free`，`https://openrouter.ai/api/v1`，model
  `minimax/minimax-m3:free`，`openai_chat_completions`，driver `openrouter`。
- 当前较优兼容 Harness：OpenCode；其余三种适用 protocol 行和本轮生命周期样本已经在 R2 evidence
  中闭合，但不把这些 exploratory Task 视为 benchmark 样本。
- 每个可比场景用独立的 benchmark Issue，从 `main` 创建 Pi/OpenCode 两条分支；不能复用 Issue `22`
  或任何已有 canary Issue。场景需要 continue 时只在该场景自己的 Issue 内复用 lineage。
- 受控故障只使用已有 Provider 或任务生命周期控制；不打印、复制或破坏现有 credential，不为制造
  401 而覆盖现有 Provider secret。若 Host 没有预配置的 401 endpoint，则认证失败场景必须登记为
  `blocked_external_fixture`，不能伪造通过。

Task `198` 在 readiness re-verify 后但本 cohort candidate re-baseline 前被 scheduler 领取，绑定 Bundle
`123` 并在确认 identity 边界后取消；Task `199` 同样在 OpenCode candidate re-baseline 前使用了错误的
Provider 3/Bundle `124`，随后取消。两者都是 exploratory identity/config-transition 记录，不计入任何 R3
场景；Task `200` 才是修正后的 OpenCode 场景 01 样本。

Task `203` 是场景 02 的第一次 OpenCode `execute/fresh` 尝试：已进入 server HTTP session 并产生 3 对
tool 事件，但随后长期没有新的 Harness 事件，人工取消后以 `harness.failed(kind=cancelled)`、
`worker.finalization(exit_code=143)` 和 `run.failed` 收敛。它的 canonical seq `1–33`、0 usage、归档和
清理状态全部保留，作为可追溯的停滞/取消失败样本，不计入成功配对；Task `204` 是相同语义 prompt
下重新创建的独立 Issue/lineage，不复用 `203`。

### Retained terminal record

- Task `203 / Issue #27`：OpenCode Bundle `124`，attempt `task-203-attempt-1-9ef9483f7b1d`，
  `execute/fresh`；output session 为空；685.386s；in/cached/out/reasoning `0/0/0/0`；3 对 tool
  事件；canonical seq `1–33`，唯一 terminal 为 `run.failed(status=cancelled, failure.kind=cancelled)`；
  `harness.failed` seq 31，`worker.finalization` seq 32（exit 143，0/0，commit null）；archive
  `07125d84adebf434d7c30a0a7a4b578a959210ac38d57d9e840223be906277ee` / 10,945 B；MR !23 无 commit；
  container 已清理。

### Scenario 06 source-change rerun and failure-to-delivery lineage

场景 06 的原始 cohort candidate 是 Bundle `123/124`。随后源码影响了 Worker identity、交付前缓存清理和
OpenCode 的 Task-local scratch 权限，因此按影响面保留旧失败并追加 post-fix rerun；这些记录不替换前面的
benchmark 样本，也不把单个 `completed` 状态当作人工验收。Profile `4` 在
`2026-09-01 08:26:12.303309` 重新 Verify，generation `49`，之后 OpenCode 使用 Bundle `131`。

| Task | Candidate / attempt / usage | Canonical and delivery | Manual acceptance |
|---|---|---|---|
| `#223 / Issue #44` | Pi Bundle `129` (`a73fd27383944edc39d98d478c4dce992b7c5efcf74a152750ab1be3569ee061`)；`task-223-attempt-1-d824ebd9ad50`；`execute/fresh`；160.856s；in/cached/out/reasoning `51/8,081/501/null`；archive `65b4d8725742b5b11bf6161d7537cf75fb5232f74f30c50b9ad6d02bc7308b36` / 43,055 B | seq `1–216`，唯一 terminal `run.completed(success=true)`；15/15 tool；`delivery.completed` seq 214、`worker.finalization` seq 215，commit `aa78decde78cdaeb3f325bae6d53a88b0664b262`；MR !40；container 已清理 | 初始 3 个断言失败，修复后同一测试 10/10 通过；最终 branch clean，HEAD 只含 `r3-s06.py` 与 `r3-s06_test.py`，无 `__pycache__`。 |
| `#224 / Issue #45` | OpenCode Bundle `130` (`51ef78a43cc0afecf052c6723ee8d293f69894788fc04d95b7070c835cabcef3`)；`task-224-attempt-1-5bbf80d28b2e`；`execute/fresh`；140.669s；in/cached/out/reasoning `0/0/0/0`；archive `efcbe4addd7e43b387c9d648511c43425413e1338d74a2c0ac4020e53fb91456` / 24,921 B | seq `1–122`；5 tool start / 4 tool complete；`harness.failed` seq 120、`worker.finalization` seq 121、唯一 terminal `run.failed` seq 122；failure `sandbox_error`（`permission.asked` 要求交互响应）；无 commit；MR !41 初始 draft；container 已清理 | 保留为真实 OpenCode permission 边界失败，不计入成功配对。 |
| `#225 / Issue #45` | OpenCode Bundle `131` (`dc75781511e5770edcc5215beafddde34247f1b2c5d2b5254940ea6abe85051c`)；`task-225-attempt-1-7aeae9f16c25`；`execute/fresh`；173.361s；in/cached/out/reasoning `176/13,188/415/0`；archive `1b974417a5e84a337bc39219329b680e5aeb8f3c8e59db4900fe038a4e90ed12` / 57,684 B | seq `1–375`，唯一 terminal `run.completed(success=true)`；15/15 tool；`delivery.completed` seq 373、`worker.finalization` seq 374，commit `7888ef59af89a740df70c054cf3070002c4523c3`；MR !41 ready；container 已清理 | 初始 3 个断言失败，修复后同一测试 9/9 通过；清理两项 `__pycache__` 后最终 branch clean，HEAD 只含 `r3-s06.py` 与 `r3-s06_test.py`。 |

`#224 → #225` 是同一 Issue 内的 failure→delivery lineage：失败样本的 workspace 残留被 retry 识别并在
交付前清理，最终只发布两个目标 fixture 文件。`#225` 的 Bundle `131` 包含 commit `796fe051` 对
OpenCode `external_directory` 的最小规则修复（仅 `/tmp/**` allow，其他外部路径仍为 ask/fail-closed）；
此前共享交付修复由 `d26971ec` 验证。Pi `#223` 与 OpenCode `#225` 使用相同 Host/Profile/Provider/语义
prompt，各自使用 Harness-specific Bundle；因此这一对是源码影响面下的 post-fix 场景 06 配对，而不是
对原始 `123/124` candidate 的静默改写。

## Acceptance and evidence contract

每个 Task 完成或进入 terminal 后，登记以下字段：Task/Issue ID、Harness、Bundle/attempt、task mode、
session mode 与 input/output session、Provider snapshot、canonical seq 与唯一 terminal、failure kind、
人工验收、耗时、input/cached/output/reasoning token、tool call 数、runtime archive digest/size、Git/MR
delivery 和 Worker 清理状态。成功任务要求变更内容符合 prompt；纯分析、无改动和预期失败任务按各自
预期结果验收，不把 `completed` 状态单独当作成功。

配对门槛沿用 schema §11：Pi 相对 OpenCode 的成功率下降不超过 10 个百分点；中位耗时和 Token 不得
同时恶化超过 25%。预期 failure 场景按“分类、canonical 事件、唯一 terminal、归档和清理是否符合
预期”判断，不从分母删除。`context.compacted`、`provider.retry`、认证失败和 invalid session 若未
被真实触发，场景保持 `not_triggered`/`blocked_external_fixture`，R3 不得标记为通过。

## Frozen 20 scenarios

Task ID 留空表示尚未执行；正式执行过程中只追加结果，不改变场景定义或删除失败样本。

| # | 场景与固定验收 | Pi Task(s) / Issue | OpenCode Task(s) / Issue | 状态 |
|---:|---|---|---|---|
| 1 | `plan` 模式：只读检查并返回计划，无代码变更、无 Git delivery | `#201 / Issue #25`；Bundle `123`；attempt `task-201-attempt-1-577ce4a8347c`；`plan/fresh`；output session `01a05b5c-a43b-7525-a72e-88834b361e25`；522.924s；in 101 / cached 6,096 / out 1,610 / reasoning null；11 对 tool 事件；seq 1–935，唯一 terminal `run.completed(success=true)`；`provider.retry` seq 56 (`engine_error`，随后成功)；0/0，commit null；archive `1724105c28854e501af9f0f012a07214d37830efda320925cf276570ea5629ce` / 75,289 B；container 已清理 | `#200 / Issue #24`；Bundle `124`；attempt `task-200-attempt-1-8d29ba0b9e28`；`plan/fresh`；output session `ses_fa4ac31ecffe1UmB3S3VmA3oEU`；220.785s；in 101 / cached 10,417 / out 1,837 / reasoning 0；7 对 tool 事件；seq 1–905，唯一 terminal `run.completed(success=true)`；0/0，commit null；archive `cc4df4e4d68e9dd32fbf73cc3e796b7735688fa0c3af5038cbdc16b8d91c0fdb` / 85,968 B；container 已清理 | pass（两边均通过只读验收，无 Git commit/diff；Issue 上的初始 MR 是 plan/execute 共用的 pre-run tracking 生命周期，不计为 commit delivery；Pi 记录 1 次真实 retry） |
| 2 | `execute` 模式：完成一个最小、可验收的单文件变更并 delivery | `#202 / Issue #26`；Bundle `123`；attempt `task-202-attempt-1-63cdebe66ea8`；`execute/fresh`；output session `01a05b6b-28ea-7529-a6cb-8c6feb0d8943`；443.414s；in 95 / cached 2,638 / out 199 / reasoning null；7 对 tool 事件；seq 1–194，唯一 terminal `run.completed(success=true)`；`provider.retry` seq 45 (`engine_error`，随后成功)；1/0，commit `2c110cb57762415faf19b224f097e5f295c5742a`；archive `aff00463349bd022dc16adb36963c741ed9d86d0d73b8304118ae0809675a7f5` / 19,482 B；MR !22 `in_review`；container 已清理 | `#204 / Issue #28`（首次尝试 `#203 / Issue #27` 停滞取消，失败证据保留且不计入成功配对）；Bundle `124`；attempt `task-204-attempt-1-db897b7cbd8b`；`execute/fresh`；output session `ses_fa4878450ffepy3SfdOdvqOc5Q`；154.833s；in 114 / cached 8,684 / out 159 / reasoning 0；7 对 tool 事件；seq 1–143，唯一 terminal `run.completed(success=true)`；1/0，commit `c926b7ecb8a9f5331602b7b9c78dabdd8f868a3b`；archive `d489331989004d62fbe8ca03abf1da5660388c5d9f55a28826cd18a8f4ac9339` / 22,931 B；MR !24 `in_review`；container 已清理 | pass（两边均创建唯一 `r3-s02-marker.txt` 并完成单文件验收；Pi 有 1 次真实 `provider.retry`；Issue 上的初始 MR 是 plan/execute 共用的 pre-run tracking 生命周期，不计为 Git commit delivery；#203 的停滞取消不从失败记录中删除） |
| 3 | `freeform` 模式：完成一个最小、可验收的单文件变更并 delivery | `#205 / Issue #29`；Bundle `123`；attempt `task-205-attempt-1-c7362711a113`；`freeform/fresh`；output session `01a05b86-3118-78b3-ba66-c19d931ec050`；111.955s；in 149 / cached 1,713 / out 78 / reasoning null；3 对 tool 事件；seq 1–68，唯一 terminal `run.completed(success=true)`；1/0，commit `116ab830ebeb7646b4141f26885ae2c2c79707f4`；archive `21dd54c69bd989872e77693ad6343f4e16705ff1fcabb173c33f07449886aae3` / 8,988 B；MR !25 `in_review`；container 已清理 | `#206 / Issue #30`；Bundle `124`；attempt `task-206-attempt-1-7ffd7bbe93e5`；`freeform/fresh`；output session `ses_fa4783e89ffeYzWQqnA8E0jzr9`；128.508s；in 134 / cached 8,044 / out 32 / reasoning 0；4 对 tool 事件；seq 1–54，唯一 terminal `run.completed(success=true)`；1/0，commit `6292751de16e27ed62230b9bf8b9aec310fd5972`；archive `bbb1b1e8768a513e7fe91de6bdb1def89820c8af5053d98dbb4c4a6edb93c6bf` / 13,015 B；MR !26 `in_review`；container 已清理 | pass（两边均创建并验证唯一 `r3-s03-marker.txt`，内容为 `r3-s03-ok`，无其他文件修改，并成功 delivery） |
| 4 | 工具成功：执行只读 shell 检查后完成标记文件；tool start/complete 成对出现 | `#207 / Issue #31`；Bundle `123`；attempt `task-207-attempt-1-d9d2c17503c0`；`execute/fresh`；output session `01a05b8f-0f1b-76e1-867d-0c79ba6048db`；167.550s；in 228 / cached 3,149 / out 526 / reasoning null；8 对 tool 事件；seq 1–306，唯一 terminal `run.completed(success=true)`；1/0，commit `0eeaae5551d76a83ed1e15e817525cd564ddd8f0`；archive `d6f7621e3937f4e02b83ed3f6056862391ba88c2b887b90fc986956b1d1c2fc3` / 29,347 B；MR !27 `in_review`；container 已清理 | `#208 / Issue #32`；Bundle `124`；attempt `task-208-attempt-1-8d9d3a7d9196`；`execute/fresh`；output session `ses_fa47002eeffeD1G0szjhjLV1OE`；166.149s；in 133 / cached 10,512 / out 314 / reasoning 0；10 对 tool 事件；seq 1–283，唯一 terminal `run.completed(success=true)`；1/0，commit `a98fccffdef1ec1834a0969487deaab45ba89c5d`；archive `f986a96382e00e2c14d886d22806c46c76e75f11c71029720e820e5b0d409089` / 39,605 B；MR !28 `in_review`；container 已清理 | pass（两边均先完成成功的只读 shell 检查，再创建并验证唯一 `r3-s04-marker.txt`，并成功 delivery；#207/#208 的 tool start/complete 分别为 8/8、10/10，期间的无害路径探测错误保留在 TaskLog，不影响 terminal） |
| 5 | 工具失败：执行一个明确预期失败的无害命令，继续完成标记文件；失败不污染 terminal | — | — | pending |
| 6 | 测试修复：建立/识别一个失败测试，修复后重新运行并交付通过结果 | `#223 / Issue #44`；Bundle `129`；attempt `task-223-attempt-1-d824ebd9ad50`；`execute/fresh`；seq `1–216`；15/15 tool；archive 43,055 B；commit `aa78dec…`；MR !40 | `#225 / Issue #45`；首轮 `#224` 为保留的 OpenCode `permission.asked` / `sandbox_error` 失败（Bundle `130`，seq `1–122`），retry Bundle `131`；attempt `task-225-attempt-1-7aeae9f16c25`；`execute/fresh`；seq `1–375`；15/15 tool；archive 57,684 B；commit `7888ef5…`；MR !41 ready | pass（两边均记录初始失败与同一测试成功重跑；最终只含两个 fixture 文件且无 Python cache；#224 失败证据保留） |
| 7 | 无改动：`execute` + `require_changes=false`，只读检查，完成且无 commit/diff | — | — | pending |
| 8 | resume/continue：fresh seed 后在同一 Issue/lineage continue，两个 Task 均可追溯 | — | — | pending |
| 9 | 稳定态取消：确认 attempt/container/tool 已初始化后取消；`cancelled`、SIGTERM、清理 | — | — | pending |
| 10 | timeout/SIGKILL：临时使用最小可保存 timeout，任务阻塞并由 runner 收敛，恢复配置 | — | — | pending |
| 11 | context compaction：长上下文任务必须产生 `context.compacted`，其后仍有唯一 terminal | — | — | pending |
| 12 | rate limit：使用已有受限 Provider，记录 `provider.retry` 与 `rate_limited` 分类 | — | — | pending |
| 13 | authentication failure：只接受真实 401/`authentication_error`；无 401 fixture 不得伪造 | — | — | pending |
| 14 | network/invalid session：真实断线或非法 Session，记录 retry/engine 或 invalid-session 分类 | — | — | pending |
| 15 | longest-context：长输入/多轮任务记录 usage、compaction 边界和完成/失败结果 | — | — | pending |
| 16 | 多文件重构：小型 fixture 的多文件一致性改造，测试、commit、push/MR | — | — | pending |
| 17 | 单文件 bug fix：只改目标文件，测试/验收通过并 delivery | — | — | pending |
| 18 | 纯分析：只读仓库并输出分析，无写入、commit 或 delivery | — | — | pending |
| 19 | 失败后公共 delivery：第一轮保留失败证据，后续修复/重试成功 delivery，顺序可追溯 | — | — | pending |
| 20 | 高 token 生成：明确的长输出/多文件生成，记录 usage、耗时和 delivery | — | — | pending |

## Execution ledger

下表只登记已经完成或明确终止的场景摘要；详细 raw archive、TaskLog、canonical event 和 UI 证据按
Task ID 追溯，不把凭据写入文档。

| Pair | Pi | OpenCode | Same prompt/Provider | Result / note |
|---:|---|---|---|---|
| 1 | `#201 / Issue #25` — completed；Pi Bundle `123`；0/0；522.924s；in 101 / cached 6,096 / out 1,610；11 对 tool；seq 1–935；archive 75,289 B；MR !21 无 commit | `#200 / Issue #24` — completed；OpenCode Bundle `124`；0/0；220.785s；in 101 / cached 10,417 / out 1,837；7 对 tool；seq 1–905；archive 85,968 B；MR !20 无 commit | frozen Provider `7 / openrouter-free`, `plan/fresh`, same semantic prompt | pass（只读结果和无变更验收通过；Pi 有 1 次 `provider.retry` 后成功；MR 为 pre-run tracking artifact） |
| 2 | `#202 / Issue #26` — completed；Pi Bundle `123`；1/0；443.414s；in 95 / cached 2,638 / out 199；7 对 tool；seq 1–194；archive 19,482 B；MR !22；commit `2c110cb5…` | `#204 / Issue #28` — completed；OpenCode Bundle `124`；1/0；154.833s；in 114 / cached 8,684 / out 159；7 对 tool；seq 1–143；archive 22,931 B；MR !24；commit `c926b7ec…`；`#203 / Issue #27` 为保留的首次停滞取消失败 | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic marker prompt | pass（#202/#204 均为唯一 marker 文件并成功 delivery；#202 有 1 次 `provider.retry`；#203 canonical 失败链路保留，不计入成功配对） |
| 3 | `#205 / Issue #29` — completed；Pi Bundle `123`；1/0；111.955s；in 149 / cached 1,713 / out 78；3 对 tool；seq 1–68；archive 8,988 B；MR !25；commit `116ab830…` | `#206 / Issue #30` — completed；OpenCode Bundle `124`；1/0；128.508s；in 134 / cached 8,044 / out 32；4 对 tool；seq 1–54；archive 13,015 B；MR !26；commit `6292751d…` | frozen Provider `7 / openrouter-free`, `freeform/fresh`, same semantic marker prompt | pass（两边均完成唯一 marker 文件验收和 delivery） |
| 4 | `#207 / Issue #31` — completed；Pi Bundle `123`；1/0；167.550s；in 228 / cached 3,149 / out 526；8 对 tool（8/8）；seq 1–306；archive 29,347 B；MR !27；commit `0eeaae55…` | `#208 / Issue #32` — completed；OpenCode Bundle `124`；1/0；166.149s；in 133 / cached 10,512 / out 314；10 对 tool（10/10）；seq 1–283；archive 39,605 B；MR !28；commit `a98fccff…` | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic tool-success prompt | pass（两边都有成功只读检查和 marker delivery；观察到的路径探测错误不影响 tool pairing/terminal，详情见 TaskLog） |
| 5 | — | — | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic tool-failure prompt | pending |
| 6 | `#223 / Issue #44` — completed；Pi Bundle `129`；1/0；160.856s；in 51 / cached 8,081 / out 501；15 对 tool（15/15）；seq 1–216；archive 43,055 B；MR !40；commit `aa78dec…` | `#225 / Issue #45` — completed；OpenCode Bundle `131`；1/0；173.361s；in 176 / cached 13,188 / out 415；15 对 tool（15/15）；seq 1–375；archive 57,684 B；MR !41；commit `7888ef5…`；`#224` 为保留的首轮 sandbox_error 失败 | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic test-repair prompt | pass（failure→delivery 顺序可追溯；两边最终均只含两个 fixture 文件；OpenCode 的 `/tmp/**` 权限修复和交付前 Python cache 清理均有真实 Host 证据） |
| 7–20 | pending | pending | frozen above | cohort execution not complete |

## Current stop boundary

- 远端磁盘当前未满；镜像、容器和 BuildKit cache 只在确有空间压力且逐项核对 container ancestry 后清理，
  不执行 broad prune。
- 当前没有运行中的任务时才切换全局 timeout；每次 timeout/cancel 样本结束后恢复 `1,800s`，并复核
  `pending/queued/running` 为空。
- 任一 Task 的实际 Profile、Image、Kit、Bundle、Provider protocol、attempt 或 Host platform 与本节
  不一致，立即停止该场景并保留失败证据。
- R3 只有 20 个场景全部有完整配对证据、统计和人工验收后才关闭；其后才进入 R4 UI/运维评审。
