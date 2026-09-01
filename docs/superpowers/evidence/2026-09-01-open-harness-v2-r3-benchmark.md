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
| 2 | `execute` 模式：完成一个最小、可验收的单文件变更并 delivery | — | — | pending |
| 3 | `freeform` 模式：完成一个最小、可验收的单文件变更并 delivery | — | — | pending |
| 4 | 工具成功：执行只读 shell 检查后完成标记文件；tool start/complete 成对出现 | — | — | pending |
| 5 | 工具失败：执行一个明确预期失败的无害命令，继续完成标记文件；失败不污染 terminal | — | — | pending |
| 6 | 测试修复：建立/识别一个失败测试，修复后重新运行并交付通过结果 | — | — | pending |
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
| 2–20 | pending | pending | frozen above | cohort execution not complete |

## Current stop boundary

- 远端磁盘当前未满；镜像、容器和 BuildKit cache 只在确有空间压力且逐项核对 container ancestry 后清理，
  不执行 broad prune。
- 当前没有运行中的任务时才切换全局 timeout；每次 timeout/cancel 样本结束后恢复 `1,800s`，并复核
  `pending/queued/running` 为空。
- 任一 Task 的实际 Profile、Image、Kit、Bundle、Provider protocol、attempt 或 Host platform 与本节
  不一致，立即停止该场景并保留失败证据。
- R3 只有 20 个场景全部有完整配对证据、统计和人工验收后才关闭；其后才进入 R4 UI/运维评审。
