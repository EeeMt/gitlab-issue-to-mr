# Open-Harness V2 R3 Benchmark Cohort

**冻结日期：** 2026-09-01  
**状态：** cohort 已冻结；截至 2026-09-02 已登记 19/20 个场景的 formal Pi/OpenCode Task pair，R3 未完成前不进入 R4/R5。

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

### Post-fix Pi native session control (impact evidence)

这是一组针对 Pi session-path 修复的影响面验证，不替换已经冻结的 20 场原始 cohort，也不把修复前的
失败样本删除。源码修复 revision 为 `e33df7e6`：Pi Adapter 将 lineage 中的 session ID 精确解析为
持久化 JSONL 文件，向 Pi 0.84.2 发送原生 `new_session` + `parentSession` 绝对路径；父文件缺失时在
spawn 前 fail-closed；同时只从 owner 发出的成功 `get_state` 捕获最新 active session ID。Pi focused
suite `test_pi_owner.py` + `test_pi_harness_adapter.py` 为 `63 passed`，`pi-run.sh` shell syntax check
通过。

本次真实 Host 验证先重新核对 Profile 4：generation `52`，verified at
`2026-09-01 15:06:55.444794`，Worker Kit `0.6.11` at
`/opt/codify/worker-kits/0.6.11-linux-amd64-b4b6321fb399`，Pi adapter digest
`c7f81e811affe51ea2af5bcb4bd37b784a00218b55fb2e9fa0cd40836cd6f4eb`，OpenCode adapter digest
`53666f397a208e5e136d673da6031d01f7cedf014081f5312677035148cf7b63`。受影响任务使用 Bundle `136`
（digest `82be21c1ef4a7a35f0f2e2429dd7651272749b2451fff38269afd8d5e0c994ee`）和同一冻结 Provider
`7 / openrouter-free`；Worker image 和 Kit identity 与 Frozen runtime 小节一致。

- #287 / Issue #86 是 `plan/fresh`，attempt `task-287-attempt-1-4cebd64798ba`，耗时
  `129.031s`，canonical seq `1–109`，3/3 tool，usage `1003/1938`，0 changes，output session
  `01a05d86-b394-7f4b-a4df-37045c6f51e0`，唯一 `run.completed`，archive
  `fc3df9cc6001fe9e7817848fd42a220a162bc63d2467c1ae2e07f88e8678bfd1` / `30,887 B`。
- #288 / Issue #86 是 `plan/continue`，attempt `task-288-attempt-1-1f1a582dab3e`，耗时
  `263.546s`，canonical seq `1–1651`，10/10 tool，`provider.retry=1`，usage `3912/3722`，0 changes；其
  `input_session_id` 精确等于 #287 output，output session 为
  `01a05d8d-a7de-7299-b7b8-5ef928aef8a0`，唯一 `run.completed`，archive
  `7de904c321d6772e2cadfe0bef4d24d93463cb10f19e05ef4722729e7bf1184b` / `149,461 B`。
- Host shared `pi-home/sessions` 同时存在 #287 和 #288 的 JSONL。#287 文件 header 的 `id` 等于
  DB output；#288 文件 header 的 `id` 等于 DB output，并含
  `parentSession=/opt/codify-issue-shared/pi-home/sessions/2026-09-01T15-11-44-020Z_01a05d86-b394-7f4b-a4df-37045c6f51e0.jsonl`。
  #288 脱敏 RPC 归档的 response 顺序为 `new_session → get_state → prompt → get_state`，最终
  `get_state` 指向该 child 文件；其 event receipts 有唯一 `harness.completed`、
  `delivery.completed` 和 `run.completed`，attempt 最终 `closed`。

修复过程中的中间样本也保留：旧的 session-ID 捕获逻辑使 #285 的 DB output 与 Host 最终文件 ID 不同；
随后 #286 使用这个错误 ID，被新 resolver 正确拒绝为 `protocol_error: Pi parent session is not
available`，没有启动 Pi。它们分别是 archive `878b589c638cf8f3780040c1bcbdc988728ed638eb8b7b0099a8d7b6b68f9015`
/ `81,642 B` 和 `bcbbfdce64ef105829cae181a741f3c69e8ff1e8f0869081f14644c482924777` / `2,880 B`。
这解释了为何必须同时修正原生 parent path 和 active session ID capture，不能只凭 #287 单次 fresh 成功
判断 continue 已正确。

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

### Scenario 05 tool-failure acceptance and OpenCode exit classification

场景 05 的固定语义是：以 standalone shell tool call 执行无害的 `sh -c 'exit 7'`，让该 tool
明确返回非零并继续完成唯一标记文件；预期 tool failure 不得把 Harness 或 Task terminal 污染成失败。
本轮保留了两组发现过程，并只把修复后的 Pi/OpenCode 样本登记为 pass。

#### Initial masked-exit samples (retained)

- `#226 / Issue #46`（Pi，Bundle `132`，digest
  `2a5439e1dd05c90929a30faff766a864599bfb44d5d0a962d5bd0f5ba265da0a`；attempt
  `task-226-attempt-1-ee8c5176c87b`；`execute/fresh`；173.212s；in/cached/out/reasoning
  `152/2,805/399/null`；seq `1–254`，7/7 tool，唯一 terminal `run.completed`；commit
  `2b528636acf3bb3da3f67b9737d68e1a30b3a9fb`，MR !42；archive
  `1bc661765278114edc551ff4ee7a1a777d76b5111685b4c106940ad8013a710c` / 24,778 B）将
  `exit 7` 与后续 `echo` 放在同一 shell tool call 中，因而该预期失败没有形成 `error=true`；随后
  的 `xxd` 缺失产生了一个非预期 tool error。任务仍只交付 `r3-s05-marker.txt`，但不计为场景通过。
- `#227 / Issue #47`（OpenCode，Bundle `131`，digest
  `dc75781511e5770edcc5215beafddde34247f1b2c5d2b5254940ea6abe85051c`；attempt
  `task-227-attempt-1-2e2a3cfc6725`；155.255s；in/cached/out/reasoning
  `50/8,178/202/0`；seq `1–47`，4/4 tool，唯一 terminal `run.completed`；commit
  `063a491d0cea4be7c4ead522e389fb3d62771405`，MR !43；archive
  `6f72dbdd45d80904e01c2be250c83e63713f3b2b424d899bbeaac9b2dd261156` / 13,751 B）同样掩盖了
  非零退出，canonical tool event 没有 `error=true`，因此不计为场景通过。

#### Strict rerun and bug discovery

- `#228 / Issue #48`（Pi，Bundle `132`；attempt `task-228-attempt-1-11cefcad3fda`；172.820s；
  in/cached/out/reasoning `105/2,734/638/null`；seq `1–346`，7/7 tool；seq 47 的 standalone
  `sh -c 'exit 7'` 为 `error=true`，随后 `harness.completed`、delivery 和 `run.completed` 均成功；
  commit `01ae03e5cfa65973f0d74da9263f00569171aaf6`，MR !44；archive
  `f3c95876cecc650e42f9e67e72c8e96ed9884a517fce9c31ada254dddaa1e9ba` / 31,543 B）。最终 branch
  clean，除 `README.md` 外只含 `r3-s05-strict-marker.txt`，内容为 `r3-s05-strict-ok`。
- `#229 / Issue #49`（OpenCode，Bundle `131`；attempt `task-229-attempt-1-f841e67206df`；
  155.255s；in/cached/out/reasoning `82/8,212/428/0`；seq `1–211`，4/4 tool；seq 10 已携带
  `exit_code=7`，但错误标记仍是 `false`；任务 terminal/delivery 成功但人工验收失败；commit
  `478a8343d42b49ab79b100ece80f1224bd918e41`，MR !45；archive
  `1bc5366ba561e3b9ce965d89a73f8f3b4f524c13e0bc17ab6a960e26ee4051ea` / 27,154 B）。这确认根因在
  OpenCode translator 只按 status/error 字段判定 tool failure，未把非零 exit code 纳入判定。

源码修复提交为 `0b4cb177`：`message.part.updated` 和 `session.next.*` durable 两条 OpenCode
路径都将整数非零 `exit_code` 映射为 `tool.completed.error=true`，并保留退出码；对应 adapter 单测
覆盖正常退出、exit 7 和 durable 结果。修复后 Profile 4 Verify 为 generation `50`，OpenCode
adapter digest `914e3b11f91c658e99643a616287f67fa9cc2d11cf4fba55f4d3d5832fdcb6f2`。

#### Post-fix OpenCode delivery

`#231 / Issue #50` 使用修复后的 OpenCode Bundle `133`，digest
`722979f2e969a39f9fdfad44b7aa7a6955002e3f4ea46989333a3ec9bc83c7dd`；attempt
`task-231-attempt-1-1a8a35382d1b`；`execute/fresh`，task snapshot 固定 Agent `build`、allowlisted
command `codify`；144.059s；in/cached/out/reasoning `205/8,319/331/0`；seq `1–170`，4/4 tool，
diagnostics 16；seq 22 的 standalone `sh -c 'exit 7'` 为 `error=true, exit_code=7`，之后 seq 166
`harness.completed`、seq 168 `delivery.completed`、seq 169 `worker.finalization(exit_code=0)` 和
seq 170 `run.completed(success=true)` 全部收敛。commit `ef716981b002bd001553688f765c83b05d2accfd`，
MR !46；archive `f1f418be1cff9d8477e6917e671fb3f768830c7120a63312fae2d6e59d1631f2` / 23,736 B。
最终 branch clean，除 `README.md` 外只含 `r3-s05-strict-marker.txt`，内容为 `r3-s05-strict-ok`；
所有 #226–#231 worker container 均已清理。

因此场景 05 以 Pi `#228` + 修复后 OpenCode `#231` 登记为 pass；#226/#227 的 completed-but-
semantically-invalid 样本，以及 #229 暴露 adapter 缺陷的样本均保留，不从记录中删除。

### Scenario 07 no-change acceptance

场景 07 的固定语义是 `execute` + `require_changes=false`：Harness 只能读取 `README.md`、检查
`git status` 并返回结果，不得写入、提交或推送任何文件。Pi 与 OpenCode 使用相同的只读 prompt、
Provider `7 / openrouter-free`、Profile 4 `v2-canary-0.6.11-four-harness` 和 fresh session，
分别使用各自的冻结 Bundle；两边均完成而没有 Git commit/diff。

- `#232 / Issue #51`（Pi，Bundle `134`，runtime bundle digest
  `df785a1a7eb1dd0206a424f1858e118b0e0056147e3bb3c1d263f188a9f6bb42`；attempt
  `task-232-attempt-1-434e1c03d681`；`execute/fresh`；output session
  `01a05c48-2f5f-7c6c-8a1c-610d993c401d`；108.496s；in/cached/out/reasoning
  `1,368/2,057/320/null`；seq `1–46`，2/2 tool，raw log 4 chunks / 2,431 B；Profile Verify
  generation `50`，Pi adapter digest `9425b09721f3840f9228b236821164dd3c0ee7cb9e77fbe4ad5b91f360ea542c`；
  seq 14/15 的 `Bash` 与 seq 23/24 的 `Read` 均成功；seq 40 `agent_settled`、seq 42
  `harness.completed`、seq 43/44 delivery、seq 45 `worker.finalization` 和 seq 46
  `run.completed(success=true)` 收敛；delivery `exit_code=0, commit_sha=null`，finalization
  `0/0`；archive `f155c06fc799222c5e260af2f4b6f25a990ec90cd6f7ad2f8e534eed7049e3a2` / 14,384 B；
  远端 branch HEAD 为初始 commit `614efffc44bfed60b82aaef33b1b7c39bdf0596d`，工作区 clean，根目录仅有
  `README.md`，container 已清理；MR !47 是无 commit delivery 的 tracking artifact）。
- `#233 / Issue #52`（OpenCode，Bundle `133`，runtime bundle digest
  `722979f2e969a39f9fdfad44b7aa7a6955002e3f4ea46989333a3ec9bc83c7dd`；attempt
  `task-233-attempt-1-c479e0c4e54a`；`execute/fresh`；output session
  `ses_fa3b19647ffe0KfmkvW5JTCzgE`；task snapshot 固定 Agent `build`、allowlisted command
  `codify`；138.661s；in/cached/out/reasoning `1,681/8,153/318/0`；seq `1–172`，4/4 tool，10
  diagnostics，raw log 5 chunks / 2,435 B；seq 9–12 的 `Bash`、seq 17/20 的 `Read` 和 seq
  18/19 的 `Bash` 均成功；seq 166 `agent_settled`、seq 168 `harness.completed`、seq 169/170
  delivery、seq 171 `worker.finalization` 和 seq 172 `run.completed(success=true)` 收敛；delivery
  `exit_code=0, commit_sha=null`，finalization `0/0`；archive
  `1fa612f52b695b3d1dd51e0351e2e28cd0f43eb7dde3a93ddef0d3f2c7c67407` / 27,182 B；远端 branch
  HEAD 同为初始 commit `614efffc44bfed60b82aaef33b1b7c39bdf0596d`，工作区 clean，根目录仅有
  `README.md`，container 已清理；MR !48 同为无 commit delivery 的 tracking artifact）。

因此场景 07 以 Pi `#232` + OpenCode `#233` 登记为 pass；`completed`、MR ready 或空 delivery
summary 均不替代 `require_changes=false`、canonical terminal、`0/0` diff 和远端 clean workspace
的人工验收。

### Scenario 08 resume/continue lineage

场景 08 的固定验收是：先以 `fresh` Task 创建并交付 `r3-s08-seed.txt`，再在同一 Issue/lineage
中以 `continue` Task 读取并验证 seed，追加并交付 `r3-s08-continue.txt`。两个 Task 必须能通过
`input_session_id`、`output_session_id`、previous-task metadata 和同一工作分支追溯；两个 Harness
仍使用相同的 Provider `7 / openrouter-free`、Profile 4 和各自冻结 Bundle。

#### Retained first Pi lineage (not the formal comparable pair)

Pi 的初次执行 `#234 / Issue #53` → `#235 / Issue #53` 已真实证明了 fresh→continue，但 fresh Task
使用了 UI 默认的 `require_changes=false`，而 continue Task 为 `true`；该配置差异不改写历史，样本
保留为 lineage 诊断，不作为正式可比 Pi pair。#234 使用 Bundle `134`、attempt
`task-234-attempt-1-8d51b614c097`、output session `01a05c56-5086-79cf-b5af-0117652bb432`，
`fresh`，139.789s，in/cached/out/reasoning `116/3,000/573/null`，seq `1–111`、8/8 tool、
40 diagnostics、2 次 `provider.retry`，commit `a5663e9cc85bdf751bf9d039b93eb10706bd7ca6`，
archive `60c9b32afd90dfb7cc1053d3d3eeee5582894db0e1cbabbd88a1c62ab4cff17d` / 17,433 B；#235
使用 `continue`、input session `01a05c56-5086-79cf-b5af-0117652bb432`、output session
`01a05c5b-1258-7af6-8609-bbb558a2c448`，133.930s，in/cached/out/reasoning
`238/2,956/531/null`，seq `1–335`、7/7 tool，commit `4aa38435c83486c9af4a28dc8c1dfde1e9df3399`，
archive `da521da178d3e14e1127b30e3b1b38c3634673afcc8a32c3d62003e63ef29544` / 30,580 B；最终
workspace 只含 README 与两个目标文件且 clean。

#### Formal comparable pair

- Pi `#238 / Issue #55` → `#239 / Issue #55`：两边均 `require_changes=true`、Bundle `134`，runtime
  bundle digest `df785a1a7eb1dd0206a424f1858e118b0e0056147e3bb3c1d263f188a9f6bb42`，Profile Verify
  generation `50`，Pi adapter digest `9425b09721f3840f9228b236821164dd3c0ee7cb9e77fbe4ad5b91f360ea542c`。
  fresh #238 的 attempt 为 `task-238-attempt-1-055588451bed`、output session
  `01a05c6a-3c0a-709e-afa8-467300749a8e`、149.883s、in/cached/out/reasoning
  `280/3,696/587/null`、seq `1–375`、11/11 tool、45 diagnostics、archive
  `7d9862df84f853cf916d0eb4180cf86a9d003359a5c169326a9d8e02c5b131da` / 35,026 B，delivery
  commit `5bb6f09561c43475df74d164696a6665629b8aa7`；continue #239 的 attempt 为
  `task-239-attempt-1-bcc8ea1608d6`，input session 等于 #238 output session，output session
  `01a05c6e-1cb9-783d-93b5-e2b29eb9b3c4`、137.420s、in/cached/out/reasoning
  `248/2,943/462/null`、seq `1–304`、8/8 tool、33 diagnostics、archive
  `299322f0ec1e1afa92a5a49505c79fadbdb42dd83aefbdf34f87af57f7c752b7` / 28,552 B，delivery
  commit `344f3e79e7085a4ecc706db272a4ecbb33347481`。两次 terminal 均为 `run.completed(success=true)`，
  delivery 与 finalization 均 exit 0，最终 workspace 只含 README、`r3-s08-seed.txt` 和
  `r3-s08-continue.txt`，container 均已清理。
- OpenCode `#236 / Issue #54` → `#237 / Issue #54`：两边均 `require_changes=true`、Bundle `133`，runtime
  bundle digest `722979f2e969a39f9fdfad44b7aa7a6955002e3f4ea46989333a3ec9bc83c7dd`，task snapshot
  固定 Agent `build`、allowlisted command `codify`，Profile Verify generation `50`，OpenCode adapter
  digest `914e3b11f91c658e99643a616287f67fa9cc2d11cf4fba55f4d3d5832fdcb6f2`。fresh #236 的 attempt
  为 `task-236-attempt-1-aa2d6557448d`、output session `ses_fa39fc307ffeq6zubJu20BnAi5`、140.262s、
  in/cached/out/reasoning `186/8,559/226/0`、seq `1–145`、5/5 tool、19 diagnostics、archive
  `c110f9c0c5c2c81fbdc25cc5a920a76ce3730e833bb404bb03d11131f5a8032b` / 22,667 B，delivery commit
  `94fc3a7155fb1424a453c5742cff907f7d1c71ab`；continue #237 的 attempt 为
  `task-237-attempt-1-89accd0b5583`，input/output session 均为 `ses_fa39fc307ffeq6zubJu20BnAi5`、
  132.387s、in/cached/out/reasoning `203/9,703/240/0`、seq `1–133`、4/4 tool、16 diagnostics、
  archive `5841bc4a9fa483d70942c750ea915d24da40c05d6825c8fa273076a39f54c01f` / 20,741 B，delivery
  commit `05432842f97fd1fc879a8c730cf328fa4387de7e`。fresh/continue 中的 OpenCode commit command
  tool error (`exit 128`) 均被后续 Task 事件继续处理，未污染 terminal；最终 workspace 只含 README、
  两个目标文件且 clean，container 均已清理。

因此场景 08 以正式可比的 Pi `#238/#239` + OpenCode `#236/#237` 登记为 pass；初次 Pi
`#234/#235` 的配置差异和所有 tool-level error 均保留，不把它们静默替换成正式样本。

### Scenario 09 stable-state cancellation

场景 09 的固定验收是：先确认 attempt、Worker container 和首个 tool 都已初始化，再由操作员取消；
Task 必须以 `cancelled` 收敛，canonical stream 要包含 SIGTERM 对应的 finalization（`exit_code=143`），
并且 attempt、container 和 workspace 都完成清理。取消不是通过提前终止浏览器请求或伪造状态来代替。

- Pi `#240 / Issue #56` 达成了稳定态取消：Profile 4、Pi Bundle `134`、Provider `7 / openrouter-free`、
  `execute/fresh`、`require_changes=true`，attempt `task-240-attempt-1-093430781533`。取消前已确认
  container `codify-240-issue56` 存在且 canonical seq 16 为 `tool.started`，standalone Bash 命令为
  `sleep 120`；随后 seq 17 为 `harness.failed(kind=cancelled)`，seq 18 为
  `worker.finalization(exit_code=143, commit=null, additions/deletions/total=0)`，seq 19 为唯一
  `run.failed(status=cancelled, success=false, failure.kind=cancelled, exit_code=143)`。Task 状态为
  `cancelled`，耗时 `150.515s`，`cancel_requested_at` 已持久化，archive
  `784a9e8304aec8c23954f5aad59fe7e0228129ccc545698e2b2b8702cf13ac6f` / `5,114 B`；无 commit、无变更，
  attempt control 已 closed，container 已清理。
- OpenCode `#241 → #242 → #243 / Issue #57` 与独立短 prompt 的 `#244 / Issue #58` 均未达到稳定态：
  分别使用 OpenCode Bundle `133`、Profile 4、冻结 Provider 和 `build/codify` 任务快照，attempt 的
  `last_seq=4`，唯一 terminal 均为 `run.failed`，control 均为 `closed`，但没有任何 `tool.started`。
  #241–#244 的耗时分别为 `134.258s`、`126.870s`、`127.267s`、`135.584s`，均为
  `protocol_error`（OpenCode bridge 对 loopback command 请求 `urllib` read timeout）；归档分别为
  `c05f4be8b382e301311e48ce44953211b66417294f4c8393d7f40dc3f8f5f865` / `3,688 B`、
  `e576bbb00e812703bb785d2a7b7ffd1eaf65323702994988b1bce76c13dc9a95` / `3,793 B`、
  `19b8dfee51025edb2d0ff86b02d5dae52a02ddbe06edc62c3d647744a38634dd` / `3,790 B`、
  `82d4a3d10b367b5680a97b390ab52427e9fd2df2e842aae14b32c58f2c136d25` / `3,651 B`；均无 commit，
  Worker container 均已清理。#244 使用 `sleep 90` 的更短 prompt 复现同一首工具调用前超时，因此当前
  证据指向冻结 Provider/endpoint 的外部 fixture 不可用，而不是场景 prompt 长度；这些失败样本全部保留，
  不计为场景通过，也不把 OpenCode 半边改记为取消成功。

- 外部 fixture 恢复后追加 OpenCode `#275 / Issue #57`，attempt
  `task-275-attempt-1-955ba767a304`。在确认 container `codify-275-issue57`、attempt 和首个工具后，
  seq 8 为 `tool.started(Bash: sleep 120)`；操作员随后从 Task UI 发出取消，seq 10 为
  `harness.failed(kind=cancelled)`，seq 11 为 `worker.finalization(exit_code=143, diff=0/0)`，seq 12
  为唯一 `run.failed(status=cancelled, failure.kind=cancelled, exit_code=143)`。Task 耗时 `157.670s`、
  0/0、无 commit，archive `52d4893b0a8468670e7d7638962e5a2ec0218bf573530463faec83a9c0686648` /
  `7,148 B`，attempt closed 且 container 已清理。

因此场景 09 现在以 Pi `#240` + OpenCode `#275` 登记为 `pass`；#241–#244 的首工具前 protocol
failure 仍作为历史失败证据保留，不从 cohort 删除。

### Scenario 10 timeout/SIGKILL convergence

场景 10 的固定验收是：在没有 `pending/queued/running` Task 时，把可保存的全局 Task Timeout 临时从
`1,800s` 调整到最小值 `60s`，运行首个 standalone `sleep 180`，由 runner 触发 timeout 并完成 TERM/KILL
收敛；样本结束后恢复 `1,800s`，且不留下 Worker container 或 workspace 变更。两边都使用冻结 Provider
`7 / openrouter-free`、Profile 4、各自冻结 Bundle 和 `require_changes=true`。

- Pi `#245 / Issue #59` 使用 Bundle `134`、runtime bundle digest
  `df785a1a7eb1dd0206a424f1858e118b0e0056147e3bb3c1d263f188a9f6bb42`、attempt
  `task-245-attempt-1-078f64dfad02`、`execute/fresh`，耗时 `144.750s`，usage
  `in/cached/out/reasoning=1,713/128/47/null`，raw log `3 chunks / 2,167 B`。canonical seq `1–22`，
  event count 为 `diagnostic=5`、`message.delta=8`、`usage.updated=2`、`tool.started=1` 及各一个
  `run.started`、`model.resolved`、`harness.failed`、`worker.finalization`、`run.failed`；seq 19 为
  `tool.started(Bash: sleep 180)`，seq 20 为 `harness.failed(kind=timeout)`，seq 21 为
  `worker.finalization(exit_code=143, commit=null, diff=0/0)`，seq 22 为唯一
  `run.failed(status=failed, failure.kind=timeout, exit_code=143)`。Task 无 commit、无变更，archive
  `871202ca0e4f06e70ca5c12da2060e6a7743254cf598eb341e0650a6085a1d9d` / `5,447 B`，attempt closed，
  container 已清理。
- OpenCode `#246 / Issue #60` 使用 Bundle `133`、runtime bundle digest
  `722979f2e969a39f9fdfad44b7aa7a6955002e3f4ea46989333a3ec9bc83c7dd`、attempt
  `task-246-attempt-1-2d40ba54e123`、固定 Agent `build`/allowlisted command `codify`、`execute/fresh`，
  耗时 `144.617s`，usage `in/cached/out/reasoning=0/0/0/0`，raw log `4 chunks / 2,218 B`。canonical
  seq `1–18`，event count 为 `diagnostic=3`、`message.delta=9`、`tool.started=1` 及各一个
  `run.started`、`harness.failed`、`worker.finalization`、`run.failed`、`usage.final`；seq 14 为
  `tool.started(Bash: sleep 180)`，seq 16 为 `harness.failed(kind=timeout)`，seq 17 为
  `worker.finalization(exit_code=143, commit=null, diff=0/0)`，seq 18 为唯一
  `run.failed(status=failed, failure.kind=timeout, exit_code=143)`。Task 无 commit、无变更，archive
  `5acd83b2b39380ecf95a34840edf3e4c918990bc81d48c477570da16476b4311` / `7,682 B`，attempt closed，
  container 已清理。

两次 Task 结束后均通过 Runtime Settings 将 `task_timeout` 恢复为 `1,800s`，数据库最终值为
`1800`，且队列仍为空。因此场景 10 以 Pi `#245` + OpenCode `#246` 登记为 pass；这组样本证明了
两种 Harness 都能在已初始化 tool 的阻塞态下由公共 runner 分类为 timeout、发出 `exit_code=143` 并完成
清理，未将 wall-clock timeout 误记为用户取消。

### Scenario 11 context compaction

场景 11 的固定验收是：长上下文任务必须真实产生至少一个 `context.compacted`，压缩后仍要有唯一
terminal；若压缩后的任务本身因 delivery 或 Provider 故障结束，必须保留失败链路，并在同一 Issue/lineage
中用后续 Task 验证可恢复 delivery，不能把后续成功静默改写成原 Task 成功。长上下文 prompt 使用冻结的
Provider `7 / openrouter-free`、Profile 4 和各自冻结 Bundle。

- Pi 的 exploratory `#247 / Issue #61` 完成了 45 对 tool、seq `1–569`，但没有
  `context.compacted`；它只留下普通成功 delivery（commit `6f00b20945763bf986a292cba790935cd4338b6c`），
  不计入场景通过。其同一 Issue 的长 prompt ceiling 诊断 `#249` 也只完成 marker，未触发压缩。
- Pi 的 continuation `#250 / Issue #61` 真实产生 2 个 `context.compacted`，并出现一次
  `provider.retry(failure_kind=rate_limited)`；由于已有 marker 和 Provider 重试，最终以 delivery failure
  收敛，作为保留诊断，不替代正式样本。正式 Pi Task `#251 / Issue #63` 使用 Bundle `134`、attempt
  `task-251-attempt-1-1c690c065f1d`、`execute/fresh`，耗时 `346.875s`，Task usage
  `7,171/928`，canonical seq `1–929`。它产生 5 个 `context.compacted`：seq `462/579/696/813`
  为 `reason=overflow, will_retry=true`，seq `922` 为 `reason=threshold, will_retry=false`；随后
  `harness.completed` seq 925、delivery started/failed seq 926/927、`worker.finalization(exit_code=1)`
  seq 928 和唯一 `run.failed(failure.kind=engine_error)` seq 929。模型在完成 50 个 chunk 后等待
  Harness 再发出它已经观察到的压缩信号，因而 delivery 失败；这保留了“压缩发生且 terminal 唯一”的
  canonical 证据，但不把该 Task 单独算作可交付成功。archive
  `fc1eae18a9160022c91c3a4485c5a203591b4404f114104c668270a464fb1653` / `1,778,253 B`，无 commit，
  container 已清理。
- 同一 Issue/lineage 的 Pi recovery `#252` 使用 attempt `task-252-attempt-1-ac925daa06d3`，
  seq `1–305`、耗时 `130.617s`，完成唯一 `r3-s11-marker.txt` delivery，commit
  `38f3a61068accf6571ffd2a74d09e6976786f8d9`；archive
  `c181a4cf005cc1f888d04f865698875627e1cfceeb9eb13a95bf340503b40ce1` / `35,934 B`，container 已清理。
  该 Task 本身不重新产生压缩事件，因此只作为 `#251` 失败后的可追溯 delivery recovery。
- OpenCode 正式 `#253 / Issue #64` 使用 Bundle `133`、attempt
  `task-253-attempt-1-0a3c01ad3e68`、`execute/fresh`，耗时 `847.465s`，canonical seq `1–391`，
  `tool.started/tool.completed=41/41`，`provider.retry=4`，没有 `context.compacted`。前三次 retry
  分类为 `engine_error`，最后一次之后 seq 389 为 `harness.failed(engine_error: unknown certificate
  verification error)`，seq 390 为 `worker.finalization(exit_code=1, diff=0/0)`，seq 391 为唯一
  `run.failed`；无 commit。archive `ec852c8104664037d8fbac39e4d7a81a2b2cb5877f75a21ed3dafce5e292c961`
  / `220,592 B`，container 已清理。该结果没有达到压缩场景的前置验收，保留为冻结 OpenRouter/TLS
  外部 fixture 阻塞，不把 Provider 错误伪造成 OpenCode compaction 通过。
- 外部 fixture 恢复后追加 OpenCode `#276 / Issue #64`，attempt
  `task-276-attempt-1-1feafcb22080`。该 Task 实际完成 37/37 个 2,000 行 chunk 读取，耗时 `856.314s`，
  canonical seq `1–307`，产生 3 次 `provider.retry(failure_kind=engine_error)`，cached usage 最高
  `436,138`（最后一次 usage 为 in `14,189` / cached `436,138` / out `59`），但仍没有
  `context.compacted`；随后 seq 305 为 `harness.failed(engine_error: unknown certificate verification error)`，
  seq 306 为 `worker.finalization(exit_code=1, diff=0/0)`，seq 307 为唯一 `run.failed`。archive
  `c21e4b5d4c2ddd8f12bb52ad49da2ee3bf51d3ac40249909c3ac79a632b2cea9` / `205,787 B`，无 commit，
  attempt closed 且 container 已清理。该样本证明已越过此前首工具前失败并承受真实长上下文，但仍未
  满足 compaction 前置验收。

随后在冻结 Provider `7 / openrouter-free` 上又执行了三次正式阈值重跑，均使用 OpenCode、Profile 4、
Bundle `137`、`execute/fresh`、`require_changes=true` 和独立 Issue/branch；这些 Task 保留为正式
Scenario 11 的追加失败/未触发证据，不覆盖前述失败样本：

- `#293 / Issue #64`（attempt `task-293-attempt-1-e029851df1c4`）直接创建并读取 100,000 行文件的
  50 个连续 2,000 行 chunk，耗时 `693.971s`，canonical seq `1–902`，56/56 tool，6 次
  `provider.retry(failure_kind=engine_error)`，usage `164/316,034/494`（input/cached/output），
  无 `context.compacted`；随后 `harness.completed` → `delivery.completed`（commit
  `73b7c48f46b8d2f09ce1f842bb5d6ae443363a6f`）→ `worker.finalization(diff=1/0)` → 唯一
  `run.completed`。archive `7bf2c0013a2b208ec1e7cda42ad7ebda6a3f6986bcd45a965524119809860b3` /
  `461,284 B`，Host Worker 已清理。
- `#294 / Issue #89` 的 50 次调用实际被模型改写为 `sed | wc -l`，只验证行数而没有把 chunk 内容放入
  上下文；耗时 `255.752s`，canonical seq `1–572`，55/55 tool，最终 `run.completed`，usage
  `192/13,589/475`，无 `context.compacted`。它是保留的无效阈值探针，commit
  `0504261b15eb0fb600a7c706930ed813d0c103d3`、archive
  `0e9b2be3a5ff28e65377f8351d5e330007132d1f045261f6f5ff836457511c6d` / `78,145 B`，Host Worker
  已清理。
- `#295 / Issue #90` 禁止管道并直接读取 400,000 行文件的 50 个连续 8,000 行 chunk，耗时 `317.094s`，
  canonical seq `1–649`，58/58 tool，usage `131/143,927/538`，最终 delivery commit
  `cd5e3ce65b22d2fd2cb68d314ce3b3a5a4510d24`、`worker.finalization(diff=1/0)` 和唯一
  `run.completed`；canonical `context.compacted=0`。其最终模型文本声称“emitted”，但该词只出现在
  assistant report；归档 `event.jsonl` 没有 `type=context.compacted`，raw OpenCode 结构事件没有
  `session.compacted` 或 `session.next.compaction.ended`，Host shared log 同样没有这两个事件。archive
  `ff06e544561574bd05a9546486b8e4a90315de1b3016f5ccf838ea360a282daf` / `434,346 B`，Host Worker
  已清理。

因此 #293 和 #295 证明当前冻结 Provider 7 已能完成真实高上下文任务，之前的 TLS engine error 本轮未再
复现；但在最高约 `316,034` cached input 的直接输出样本中仍没有结构化 compaction 事件。模型最终文本、
日志中出现的 `context.compacted` 字样不能替代 raw/canonical event。当时 Scenario 11 尚未满足“压缩后
继续并唯一 terminal”的硬验收，状态保持 `blocked_external_fixture`，不把三次成功 delivery 追认为
compaction 通过；后续受控 legacy compatibility route 的最新结果见下文。

为排除“OpenCode 没有执行足够多的有效上下文输入”这一独立变量，2026-09-02 又在独立 Issue `88`
上使用已有但非冻结的 Provider `12 / openrouter-minimax-responses`（model
`minimax/minimax-m3:free`、`openai_responses`）做 alternate-provider 诊断；三次 Task 均绑定 Bundle
`137`（digest `64f713267cccc19b7730101b075df5962c89f0accfe3d67b3d29bcba4c1dbb7d`），不计入正式 cohort：

- `#290` 是 `plan/fresh`，只完成 3/3 tool、canonical seq `1–83`，没有进入 40-call probe；archive
  `c917c26240e77f0b5fc2e9ca49469ad74faf894dcdaacf678921a348b4930eee` / `21,608 B`。
- `#291` 是 `execute/fresh`，任务结果报告完成 40 次指定调用，但目标的 benchmark 文档在真实
  `kit-owned-l3` workspace 中不存在，40 次均为 `sed ENOENT`；canonical receipts 为 42/42 tool、seq
  `1–330`、耗时 `206.732s`，无 `context.compacted`，archive
  `80d7e2a35270ac1c44aa07ea6b79d162da262089979dfff2cdfbe5653469d9bc` / `47,317 B`。
- `#292` 改为读取真实存在的仓库根 `README.md`，任务结果报告完成 40 次有效只读调用；canonical
  receipts 为 46/46 tool、seq `1–370`、耗时 `248.115s`，usage 为 input `196` / cached `68,894` /
  output `118`，唯一 terminal 为 `run.completed`，workspace clean，且 `context.compacted=0`；archive
  `5a819bee2395b99f128f572924a2127c6ed2ebbae0104321ceba5d77c8b5c2b9` / `65,374 B`。归档中的
  `event.jsonl` 与 `harness-events/opencode.jsonl` 都没有 compaction event，Host shared OpenCode log
  中 `context.compacted`、`session.compacted` 和 `session.next.compaction.ended` 计数也均为 0。

这组 alternate-provider 结果说明，即使有效文件读取使 cached input 达到 `68,894`，当前 Bundle/模型
也未产生压缩事件；它既不能证明冻结 Provider `7` 的 compaction 可用，也不能替代正式失败证据。

#### 2026-09-02 native compact route / session marker probe

为排除“Task 进程拿不到 OpenCode session marker”这一运行时变量，在远端 Host 重新构建并重启
backend/scheduler 后，Profile `4` Verify generation 更新为 `53`，新任务绑定 Bundle `138`，digest
`3b53a1b2e5d2fc4cb85cfb461b041e43da6d064a38a0f88ee4c83cc54506341f`。该 Bundle 包含源码提交
`a915fb70`：`opencode-session.id` 是非 secret 的 session ID，改为允许 Task 进程读取（`0644`），
外层 adapter 仍在任务结束时清理 marker。Focused adapter suite 为 `72 passed`。

OpenCode `1.18.19` 的本地 `/doc` 明确暴露 `POST /api/session/{sessionID}/compact`，返回契约包括
`204/400/401/404/503`。在真实 Task 内使用 Task-local server 环境完成 native POST，并且只记录 HTTP
状态，不记录 credential 或响应体：

- `#296`（Provider `7`、旧 Bundle `137`）先以 `sleep` 保持 server 活跃，随后取消；外部无凭据请求得到的
  `401` 是 OpenCode Server 自身的 Basic Auth，不属于 AI Provider authentication failure，故不计入场景 13。
- `#297` 取消，原因是模型没有按验收要求把每个 chunk 的实际内容放入上下文；它不计入 compaction 证据。
- `#298`（旧 Bundle `137`、Provider `7`）成功完成 marker/请求路径并记录真实
  `compact_http_status=503`，但 canonical `context.compacted=0`，raw `session.compacted` 与
  `session.next.compaction.ended` 均为 `0`；archive `task-298-runtime-archive.tar.gz` / `60,839 B`。
- `#299` 使用已有 Provider `3 / opencode-minimax`，在进入 Harness 前真实返回 `rate_limited`（月度额度
  限制）；没有 compact 请求，不能替代 Provider `7` 的 compaction 结果。
- `#300` 使用新 Bundle `138` 和 Provider `7`；Task 进程已能读取 marker，并记录真实
  `compact_http_status=503`。其首个 fixture shell 命令实际因遗漏 `> "$FIX"` 退出 `2`，因此不能声称
  完成有效 fixture 读取；即使如此，后续 native POST 已到达 OpenCode，archive 的 canonical/raw
  compaction 计数仍为 `0`，archive `task-300-runtime-archive.tar.gz` / `24,190 B`。
- `#301` 使用已有 Provider `4 / opencode-luna`，在进入 Harness 前同样真实返回 `rate_limited`；没有
  compact 请求。
- `#302` 使用 Provider `7`、Bundle `138` 和 60,000 行 fixture；watcher 依赖 frozen Worker image 中不存在的
  `jq`，只留下 `compact_http_status=timeout`，随后由 UI 取消。它没有产生可验证的 compaction event，不能
  作为有效 fixture 样本。
- `#303` 使用同一 Provider/Bundle、12,000 行 fixture 和 grep-only watcher；任务真实收到一个
  `session.idle`，但 raw 中 13 个 tool parts 的最新状态为 12 个 `completed`、1 个 `pending`，因此 Adapter
  按既定 fail-closed 规则以 `protocol_error: OpenCode protocol failure: session.idle with active tool parts`
  收敛。canonical/raw compaction 计数均为 `0`，没有 `session.compacted` 或
  `session.next.compaction.ended`。
- `#304` 使用同一 Provider/Bundle、3,000 行 fixture，并要求模型执行两次 `sed` 读取，再由只在 idle 后
  触发的 Task-local watcher 发起探针；任务同样以 `protocol_error: ... session.idle with active tool parts`
  失败。其归档
  `event.jsonl` 只有 `harness.failed`、`run.failed`、`worker.finalization` 各 1 个，OpenCode raw 有 1 个
  `session.idle`，没有 `session.compacted`、`session.next.compaction.ended` 或 canonical
  `context.compacted`；archive `task-304-runtime-archive.tar.gz` / `50,054 B` /
  `78bb05bc8cf4fc800a5d6c8b9682b24b95348bebfb4ca65d69afb5a275e19ca8`。
- `#305` 使用同一 Provider/Bundle 做 clean-idle Task-local watcher，watcher 窗口为 120s；Task 在
  `182.517s` 正常完成，实际 watcher 状态为 `timeout`，因为任务约 3 分钟后才进入终态。其 canonical
  terminal 为 `harness.completed`、`worker.finalization`、`run.completed` 各 1 个，OpenCode raw 有
  1 个 `session.idle`，没有任何 compaction event；archive `task-305-runtime-archive.tar.gz` /
  `83,726 B` / `58c5af53908dc73a43e60865dcdec3c2663e9862d15688a712625562bd9a4938`。
- `#306` 将同一 clean-idle watcher 延长为 900s；Task 在 `201.384s` 正常完成，但 watcher 仍未在
  Task 生命周期内观察到可触发的 idle，归档中最后状态为 `timeout`。其 canonical terminal 同样为
  `harness.completed`、`worker.finalization`、`run.completed` 各 1 个，OpenCode raw 有 1 个
  `session.idle`，没有 `session.compacted`、`session.next.compaction.ended` 或
  `context.compacted`；archive `task-306-runtime-archive.tar.gz` / `91,561 B` /
  `61d956cd04be0d8f75f5710e57c416a5fee4cda1d8436abc861154a4f01a868b`。
- `#307` 使用空白容忍的 `"type"[[:space:]]*:[[:space:]]*"idle"` watcher；Task 在 `180.485s` 正常完成，
  但 detached watcher 的状态行未在归档 console 中出现，说明容器清理与后台进程仍有竞态。其 canonical
  terminal 为 `harness.completed`、`worker.finalization`、`run.completed` 各 1 个，OpenCode raw 有
  1 个 `session.idle`，没有任何 compaction event；archive `task-307-runtime-archive.tar.gz` /
  `77,423 B` / `b09ac4d47e064315379c311133c55ebe75f7c719228569589fd8b7bc9d9c4835`。
- `#308` 改由远端 Docker 主机侧观察 Task-local status，并在 idle 瞬间尝试 native compact；观察器在
  容器清理前没有拿到 HTTP 状态。Task 在 `144.362s` 正常完成，canonical terminal 为
  `harness.completed`、`worker.finalization`、`run.completed` 各 1 个，OpenCode raw 有 1 个
  `session.idle`，没有 `session.compacted`、`session.next.compaction.ended` 或
  `context.compacted`；archive `task-308-runtime-archive.tar.gz` / `23,319 B` /
  `8529294ecd6331b9384acae52ee15d97b91fde1be6b680666de169524271e11b`。

`#302/#303/#304/#305/#306/#307/#308` 是同一冻结 Provider 上对 watcher 时序、Task-local marker、
clean-idle route 和 idle fail-closed 边界的追加诊断，不是新的正式 cohort 通过样本；七次任务的 Worker
container 均已由调度器清理。

#### 2026-09-02 real Provider long-read tasks and legacy summarize route

在同一远端开发 Host 上使用已有 Provider `7 / openrouter-free`、Profile `4`、Bundle `138` 和独立
Issue `#92` 追加了两次真实 Task，目的分别是确认正常 continuation lineage 和在不依赖 watcher 的情况下
增加长上下文/有效文件读取压力：

- `#309` 为 `plan/continue`，completed，耗时 `139.560s`，canonical tool `6/6`，input/output
  token `1,943/1,857`，delivery `0/0`，archive `task-309-runtime-archive.tar.gz` /
  `2d1c02b7559a1f31d3e100fb090b593bd662078728f270deff6bbe945f887bc7` / `31,348 B`。
  raw OpenCode 只有 1 个 `session.idle`，canonical 没有 `context.compacted`。
- `#310` 为 `freeform/continue`，沿用 `#309` 的同一 session lineage，completed，耗时 `307.743s`，
  按任务指令完成 12,000 行 Task-local fixture 的 80 次有效 direct file read；canonical tool
  `82/82`，input/output token `34/214`，delivery `0/0`，archive `task-310-runtime-archive.tar.gz` /
  `9dd420a15614fc0a308431e0383e3a3b113dfafc5fc7723d0bc8e901affa7eb0` / `211,918 B`。raw 中有 80 个
  `file` 事件和 1 个 `session.idle`，没有
  `session.compacted` 或 `session.next.compaction.ended`；canonical `context.compacted=0`。

两次任务都使用真实 Provider 完成并由 Worker 正常清理，但没有产生 OpenCode compaction event，因此不
改变 Scenario 11 的 `blocked_external_fixture`。本轮一个外部 observer 因启动竞态得到 HTTP `000`；随后
在 Task 容器外不带 Task-private Server Basic Auth 请求 legacy summarize route 得到 `401`。这两个结果都
不能作为 Provider authentication failure 或 compaction 证据。

对固定 OpenCode `1.18.19` 的 exact-tag source 继续核对后，确认 legacy `POST /session/:sessionID/summarize`
与 V2 `POST /api/session/:sessionID/compact` 是两条不同路径：官方
[`session.ts` handler](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.19/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts)
要求 `providerID`、`modelID` 和可选的 `auto`，当前 App 的
[`server-compat.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/app/src/utils/server-compat.ts)
也通过该 legacy route 兼容 compact。Codify 本轮为 Bridge 增加了该请求的 URL/payload/audit transport
映射，但没有改变默认执行路径，也没有把外部未认证请求追认为有效调用；受控 in-process 认证验证见下文
`#314/#315`。

随后将该诊断收敛为默认关闭的 Task-local opt-in：只有任务在 `CODIFY_RUNTIME_DIR` 写入精确 marker
`codify.opencode.legacy-summarize/v1` 时，Bridge 才会在没有 active tool part 的第一次 `session.idle`
内用当前 Task-private Basic Auth 调用 legacy summarize；非 opt-in 任务完全不改变，active-tool idle 仍
fail-closed。远端先重新验证 Profile `4`，随后生成 Bundle `139`（`542,720 B`，digest
`838586bb9871501a39f27d665f207567aa61639ef2725ac536ec1b0c096092f5`），并确认 Task 容器中的 Bridge
摘要与本地测试版本一致。

- `#313` 使用 Provider `7`、Profile `4`、Bundle `139`、`freeform/continue`，但沿用过大的既有
  session lineage 后在 `1800s` runner timeout 收敛；archive `task-313-runtime-archive.tar.gz` /
  `17d45e2caa90e78f5be281e1f65f2f0cba674fbb9aea332fd5c7d73c7a56eed2` / `8,979 B`。raw 只有
  `session.error` 和持续 heartbeat，没有 `session.idle` 或 `session.summarize`；该失败保留为
  continuation 停滞证据，不计入 compaction。
- `#314` 改用同一 Provider/Profile/Bundle 的 `freeform/fresh` 短任务，`136.428s` 完成，usage 为
  input/output `658/352`，tool `1/1`；archive `task-314-runtime-archive.tar.gz` /
  `23507c96a5b7169879cf1ea396a6d7bbec925022a7debf3a6b8852603b009cc4` / `18,230 B`。HTTP audit
  为 `session.summarize: 200 / success`；raw 有 `session.compacted=1`、`session.idle=1`，canonical
  有 `context.compacted=2`，并且 `harness.completed=1`、`run.completed=1`，证明认证 legacy route
  能进入 Codify 的 compaction event 链路并在后续 idle 唯一收敛。
- `#315` 再用同一固定身份执行 `freeform/fresh` 长上下文任务：Task-local 12,000 行 fixture、37/37
  个有效 direct-read tool、耗时 `171.667s`，usage 为 input/output `36,499/975`；archive
  `task-315-runtime-archive.tar.gz` / `450bac375f75019924a14901f1ea496a9c0450584ffc536db4efa5b6ac987778` /
  `117,822 B`。HTTP audit 同样为 `session.summarize: 200 / success`；raw
  `session.compacted=1`（line `745`）后有 `session.idle=1`（line `748`），canonical 有
  `context.compacted=3`（lines `171/503/504`），之后才是 `harness.completed`（line `509`）和
  唯一 `run.completed`（line `513`）。这满足场景 11 的长上下文、真实 compaction event 和唯一
  terminal 硬条件；Task 为只读 probe，delivery/finalization 为 `0/0`，Worker container 已清理。

#### Pinned OpenCode upstream capability boundary

2026-09-02 对冻结 Kit 中 OpenCode `1.18.19` exact tag 的
[`compaction.ts`](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.19/packages/opencode/src/session/compaction.ts)
做了只读核对：该版本的 compaction processing 只有 automatic/overflow 路径，没有 V2 manual
compaction producer。官方上游 issue
[`#40614`](https://github.com/anomalyco/opencode/issues/40614) 记录 `SessionV2.compact` 当前为
`OperationUnavailableError`，并由 Server 映射为 `503`。这解释了 `#298/#300` 对
`POST /api/session/{sessionID}/compact` 的真实 `503`：它是固定 OpenCode build 的上游能力边界，
不是 Codify adapter 的 event-order 缺陷。

因此 V2 `/api/session/:sessionID/compact` 仍记录为固定 OpenCode build 的上游 `503` 能力边界，
不再重复同类 V2 route probe；legacy `/session/:sessionID/summarize` 则由默认关闭的 exact-marker
Bridge 诊断钩子完成了受控认证验证。该钩子只在 clean idle 且没有 active tool part 时调用一次，并
保留 `session.idle` active-tool 的 fail-closed 规则。

这组结果区分了两条路径：V2 native compact 的 `503` 仍不能作为 Codify adapter 缺陷；而 `#314/#315`
的 Bridge 内 legacy summarize 均在 HTTP audit 中记录 `session.summarize: 200 / success`，并在 raw
OpenCode 与 canonical stream 产生 compaction event。Provider `3` 与 `4` 的额度限制仍不提供可比
的认证样本，不改变 Scenario 13 的 blocker。

因此场景 11 现登记为 `pass`：Pi 半边保留正式 compaction、唯一 terminal 和同 lineage recovery
delivery；OpenCode 长上下文 Task `#315` 在冻结 Provider `7`、Profile `4`、Bundle `139` 上真实
产生 `context.compacted=3`，并在其后以唯一 `run.completed` 收敛。OpenCode `#253/#276` 的 TLS
engine error、`#293/#295` 的无 compaction、`#298/#300` 的 V2 `503`、`#302/#303/#304/#305/#306/
#307/#308` 的 watcher 边界以及 `#313` 的 continuation timeout 均作为历史失败/边界证据保留，
不覆盖最新成功样本。`#314/#315` 验证的是 legacy compatibility route 的 canonical event 链路，
不是 V2 native compact endpoint 或自然 automatic/overflow producer 的能力证明；后者仍受固定
OpenCode `1.18.19` 上游边界约束。

### Scenario 12 provider rate limit

场景 12 的固定验收是：使用已有 Provider `7 / openrouter-free`，观察真实 `provider.retry`，并在
canonical payload 中确认 `failure_kind=rate_limited`；不通过伪造响应或修改 Provider secret 制造 429。
本轮先执行了两轮独立的 Pi/OpenCode retry probe，均使用 Profile 4、各自冻结 Bundle、`execute/fresh`、
`require_changes=true` 和独立 Issue：

- 第一轮 `#254 / Issue #65`（Pi，Bundle `134`，attempt `task-254-attempt-1-a57c1bea7e08`）耗时
  `161.720s`，13/13 tool，seq `1–427`，commit `d10ab625c4516b3abdef0aa5480cb4f26fdcea27`，
  `run.completed`，archive `5d3aa408b0d66d1a347b67e15d42143e117a47c2f7ee0ddb6b647cbf52b4f521` /
  `44,906 B`；`#255 / Issue #66`（OpenCode，Bundle `133`，attempt
  `task-255-attempt-1-7d7a8df23975`）耗时 `184.648s`，8/8 tool，seq `1–318`，commit
  `29a3181a8f6b5ff058c6c07d0ab90f21aa5cb572`，`run.completed`，archive
  `570b34d96fab3d13fd00e2bc5c9ea48db612a440fa6b10c9335e72957b295dda` / `42,300 B`。
- 第二轮增加到 20 个独立检查调用：`#256 / Issue #67`（Pi，attempt
  `task-256-attempt-1-bc561a6c6ef2`）耗时 `216.145s`，26/26 tool，seq `1–592`，commit
  `f16e80eb6d06700245a92049ff5bf56313213f39`，archive
  `a4d1bbee34128832b0a6bb125c86ea7ce605074891da8f6c977f9c33e524ae5f` / `57,578 B`；`#257 / Issue
  #68`（OpenCode，attempt `task-257-attempt-1-20bc02042eb7`）耗时 `200.954s`，26/26 tool，seq
  `1–309`，commit `7b63cdc5ce6ea06c8141956a316c28102b8da2ff`，archive
  `57fb79a212de610fdf00c3a53f733526dfadf70ec36636dbdf4de70cb23ba2bd` / `49,189 B`。四个任务的
  canonical 关键事件均为 tool start/complete、`harness.completed`、delivery、`worker.finalization`
  和唯一 `run.completed`；均没有 `provider.retry`，container 均已清理。
- 同一冻结 Provider 的真实 `rate_limited` 事件已经在保留的长上下文诊断 `#250 / Issue #61` 和正式
  compaction Task `#251 / Issue #63` 中出现，但那两条 Task 属于场景 11，不把它们的 prompt、耗时或
  delivery 重复计入场景 12。它们只证明 Provider/translator 曾真实发出 `provider.retry`，并带有
  `failure_kind=rate_limited`。
- 随后在 Profile 4 readiness 重新验证后，用已有 Provider `9 / openrouter-glm52-responses` 做了受控的
  OpenCode `#317 / Issue #92` 真实诊断：Bundle `141`，attempt `task-317-attempt-1-8d36ccef7cbc`，
  `freeform/fresh`，耗时 `138.496s`，canonical seq `1–18`，5 个 `provider.retry`，usage/tool 均为 `0`。
  raw `session.error` 为 `APIError`，其 `data.statusCode=429`、`isRetryable=true`；最终唯一终态为
  `harness.failed(rate_limited)` → `worker.finalization(exit_code=1)` → `run.failed(rate_limited)`。
  runtime archive 为
  `79138197c9585d6b02f52400029ec46580338ce22630b40ffdb24da9c128169f` / `7,301 B`；local HTTP audit
  只有 `session.create=200`、`session.prompt_async=204` 和 `event.subscribe=200/closed`，不包含
  Provider 请求正文或状态；Worker container 已清理。该任务证明了真实 Provider-side `429` 与终态
  taxonomy，但不是冻结的 Pi/OpenCode 配对 formal sample，因此场景 12 仍保持 `not_triggered`，不覆盖
  已有成功样本，也不制造人工 429。
- 2026-09-02 在再次完成 Profile 4 readiness verify（generation `57`，verified at
  `2026-09-02 01:05:30.678336`）后，用冻结 Provider `7 / openrouter-free` 做了当前候选的 Pi
  控制诊断 `#318 / Issue #92`：Provider snapshot 为 `openai_chat_completions`、model
  `minimax/minimax-m3:free`，Bundle `142`，runtime bundle digest
  `fce7b89a9e5ddde76c2ae2376ed56fb799e86a16ae89da404abb5e79e51e4a6e`，attempt
  `task-318-attempt-1-7f36990dc314`，`freeform/fresh`，耗时 `104.515s`。canonical seq `1–72`，raw
  Pi archive 有 4 个 response、1 对 tool start/complete，最终 usage `83/1,659/103`
  （input/cached/output），唯一终态为 `harness.completed` → `delivery.completed(exit_code=0)` →
  `worker.finalization(exit_code=0,diff=0/0)` → `run.completed(success=true)`；没有
  `provider.retry` 或 `context.compacted`。runtime archive 为
  `3788e40f5393529a899b616993de6ae7d7624d046ac0e7b506cee0a008d8de2e` / `8,190 B`，Worker
  container 已清理。启动早期出现的短暂 `control_owner_unreachable` gate warning 没有升级为
  terminal rejection，实际 Pi response 已进入归档；该任务是当前 Provider 7/Pi 的真实成功控制样本，
  不是冻结的 formal rate-limit pair，故不改变场景 12 的 `not_triggered` 状态。

- 随后在 Profile 4 readiness generation `62`（verified at `2026-09-02 03:45:48.497974`）上，使用同一
  Provider `7 / openrouter-free` 做了两项 formal acceptance re-probe：Pi `#332 / Issue #65` 使用
  Bundle `148`（digest `0a25b854d5dd42318232968ee67b7463b8cd77782d8d52f37bb381025452c376`）、
  attempt `task-332-attempt-1-a6874f751f40`、`Implementation/fresh`，耗时 `340.002s`，canonical
  seq `1–972`、60/60 tool、usage `165/857`（input/output），commit
  `29a746e80f46b6a2685d5fda39ff2f29667b4b62`，archive
  `e5ebadfd058ff24ffb4d7f18a94b01fe4e07d4d3de6ba20a147c9a63497e9e11` / `87,639 B`；OpenCode
  `#333 / Issue #66` 使用 Bundle `149`（digest
  `ed249c6be8627d354365a1402bd11bdf7a2ad2200e3300231069dea1562ebe3e`）、attempt
  `task-333-attempt-1-9b6d1a9656c1`、`Implementation/fresh`，耗时 `346.913s`，canonical seq
  `1–817`、51/51 tool、usage `67/683`，commit `2ca9bc1b6fc8aecff6dbf6a7909519893961fbe9`，
  archive `9ed5f710ca18aad114630c1645ecf009eab6fdfdbbc74d4bb873186943412f3c` / `106,104 B`。
  两项均 completed、无 `provider.retry`/`rate_limited`，无额外 container 残留；它们补强了当前
  Provider 的成功控制和正式验收重跑，但没有制造或替代自然发生的 rate-limit 事件。

因此场景 12 当前登记为 `not_triggered`：两轮正式配对与 #332/#333 formal acceptance re-probe
均成功且没有触发 retry，#318 也只补充了当前 Provider 7/Pi 的成功控制样本，不能据此声称本场景的
rate-limit acceptance 已闭合；#250/#251 与 #317 的真实分类证据保留为关联诊断。后续若冻结 Provider
自然返回新的 rate limit，可追加正式配对 Task；不改变已有成功样本，也不制造人工 429。

### Scenario 13 authentication failure

场景 13 只接受真实的 401 / `authentication_error`，不读取或修改 Provider secret，也不通过临时错误配置
伪造认证失败。开发环境当前只读 Provider 元数据显示 Provider `3–12` 均为 enabled，没有专门的 401
fixture；本轮 #296 与 #310 的无凭据请求得到的 `401` 都是 OpenCode Server Basic Auth，不能冒充 Provider
401；#299/#301 的 `rate_limited` 也不等价于认证失败。

历史 Provider `11` 的 `#150/#151` 不能作为认证 fixture：两条 Task 的 canonical `failure.kind` 虽为
`authentication_error`，但 raw/canonical failure message 均以 `404 <!DOCTYPE html>` 开头，是上游 HTML
错误页而不是 Provider HTTP `401`。对应 archive 分别为
`f21eb03495fe6abda1ffcac50a39701fcaf6712fa878b6419a9f51638ec62391` / `270,101 B` 与
`138c75e35d538e77cca34de801d07384d2927005f42348757445f40884d465fe` / `270,088 B`；两者都不计入本场景。
当前源码提交 `ab869c67` 已移除 Pi translator 对裸词 `authentication` 的匹配，并由
`test_pi_provider_failure_message_is_bounded_and_html_does_not_fake_auth_error` 锁定该边界；这是分类回归
保护，不是一个可替代真实 Provider 401 的 fixture。

本轮追加了一个不改变 Provider secret 的真实诊断任务：OpenCode `#316 / Issue #92` 使用已有 Provider
`11 / openrouter-minimax-anthropic`、Profile `4`、Bundle `140`、`freeform/fresh`。任务确实进入了
OpenCode Server 并完成了 canonical attempt，但 `seq 1–8` 的唯一终态为
`harness.failed(engine_error)` → `worker.finalization(exit_code=1)` →
`run.failed(engine_error)`，failure message 为 `unknown certificate verification error`；usage 与
tool 均为 `0`。runtime archive 为 `725a70a8dc12dc34d9176a42082577fd0c2870c82b43bf9379d935f203555b0a`
/ `6,578 B`，其中 OpenCode HTTP audit 只有本地 `session.create`、`session.prompt_async` 和
`event.subscribe` 成功记录，没有 Provider HTTP status；Worker container 已清理。因此该任务证明了
一次真实 Provider 诊断失败，但没有到达可归类为 401 的 Provider 响应，不能替代认证 fixture，也不改变
本场景的 `blocked_external_fixture` 状态。另一个后续真实诊断 `#317` 是 Provider-side `429`，已在场景
12 记录，亦不等价于认证失败。

随后在 Profile 4 readiness generation `58`（verified at `2026-09-02 01:22:33.312620`）上，使用
已有 Provider `6 / opencode-pi` 执行了 Pi `#319 / Issue #92` 的真实诊断：Provider snapshot 为
`anthropic_messages`、`https://opencode.ai/zen/go`、model `deepseek-v4-flash`，Bundle `143`，runtime
bundle digest `ab7b89cebaa8070a19e029c333980e65d38dcaeaf69042e7b2864c7d025229e3`，attempt
`task-319-attempt-1-e8256b805dce`，`freeform/fresh`，耗时 `97.422s`。Pi raw archive 有 4 个 response、无
tool/usage；结构化 `harness-result.json` 的 failure 为 `rate_limited`，错误前缀为真实 Provider `429`
（`GoUsageLimitError`），canonical seq `1–9` 收敛为唯一
`harness.failed(rate_limited)` → `worker.finalization(exit_code=1)` → `run.failed(rate_limited)`。
runtime archive 为 `d6571e8214b8aeb7a2f5ee24e3bbffe640c98de6a435a9fc0fadbf7a094e2ef2` / `3,786 B`，
Worker container 已清理。该任务到达了 Provider 但仍没有 HTTP 401，因此不能替代认证 fixture，也不改变
本场景的 `blocked_external_fixture` 状态。待提供不改变冻结 Provider 的真实认证失败 fixture 后再补跑。

### Scenario 14 network interruption / invalid session

invalid-session 分支已使用隔离 fixture 真实执行；network interruption 分支先经过四次 bridge
断开探索，随后又用容器 network namespace 的 443 egress 阻断做了窄范围受控 probe。所有 probe
均使用已有 Provider，不读取或修改任何 Provider secret：

- OpenCode #281 / Issue #84 使用 Bundle `133`、attempt `task-281-attempt-1-b8c96260cd74`，
  `continue` 输入为不存在的 session ID，canonical seq `1–4` 以唯一
  `harness.failed(engine_error: Session not found)` → `worker.finalization(exit_code=1)` →
  `run.failed(engine_error)` 收敛；archive
  `838f07971ec3ae16d1dd2ca0466a6153dd5c7edb5a8ee1bcb71a652cc17ccac4` / `2,835 B`，无 output
  session，container 已清理。
- Pi #282 / Issue #85 是修复前保留的负面样本：未被 Pi 识别的 `parentSessionId` 使 Pi 静默创建
  fresh session，DB 记录 bogus input 与新的 output，archive
  `fbe71e57d7ae754271f31a13019133f53bfce22865c670d59eb9251e8a9ed027` / `166,892 B`；该行为
  不计为通过，且历史记录不改写。
- Pi #289 / Issue #87 使用当前 Bundle `136`、attempt `task-289-attempt-1-b5cdfed0c915`，
  `continue` 输入为 `01a05d8e-0000-7000-8000-000000000000`，耗时 `92.122s`，canonical seq
  `1–4` 以唯一 `harness.failed(protocol_error: Pi parent session is not available)` →
  `worker.finalization(exit_code=1)` → `run.failed(protocol_error)` 收敛；无 tool/usage/output
  session，archive `e7726095366d62b5b3e58f5e67d8c9f22b67673401bef74432a6b69ebfa1fc46` /
  `2,788 B`，#87 的 Host `pi-home` 目录为空，Worker container 已清理。

本轮在开发环境 `192.168.50.129` 上使用已存在的 Provider `7 / openrouter-free`、Profile `4` 和当前
V2 image 做了四次探索性网络控制；这些 Task 不追认进冻结 formal cohort：

- Pi `#320 / Issue #93`（Bundle `144`，attempt `task-320-attempt-1-570e59551a5b`，
  `freeform/continue`）在首个 `sleep 90` 工具期间断开并恢复 `bridge` 网络；任务随后以
  `harness.completed` → `delivery.completed` → `worker.finalization(exit_code=0)` →
  `run.completed` 收敛，canonical seq `1–100`、3/3 tool、usage `922/388`（input/output）、
  `317.739s`，没有 `provider.retry`。runtime archive 为
  `c95fe0bb8d048d49117f0c354cf347b7469fa86031542392a5f341ebc1f82f88` / `13,981 B`，container
  已清理。
- Pi `#321 / Issue #94`（Bundle `144`，attempt `task-321-attempt-1-5fcc6cfe5fa9`，
  `freeform/continue`）在持续 `text_delta` 期间断开并恢复 `bridge`；raw 在断线期间仍继续消费已到达
  的流数据，没有 `provider.retry`。为避免任务继续占用 Provider/worker，外部取消后 canonical seq
  `1–2,998` 以 `harness.failed(cancelled)` → `worker.finalization(exit_code=143)` →
  `run.failed(cancelled)` 收敛，`673.361s`，无 delivery；runtime archive 为
  `8a8a6e33841f8c8d84f7d9f21624f7f9effa77928facce71e85a3f0fb66772aa` / `189,541 B`，container
  已清理。
- OpenCode `#322 / Issue #95`（Bundle `145`，attempt `task-322-attempt-1-162a91693691`，
  `freeform/fresh`）在 `message.part.delta` 流式阶段断开并恢复 `bridge`；任务继续完成，canonical
  seq `1–2,167`，3/3 tool、usage `62/4,380`、`396.168s`，raw 没有
  `session.next.retried`，canonical 没有 `provider.retry`，终态为唯一 `run.completed`。runtime
  archive 为 `05e377fab2d3cffb4b523dd0ff4372a76171b5288d4cffa0f04cb25f496a0899` / `177,837 B`，
  container 已清理。
- OpenCode `#323 / Issue #96`（Bundle `146`，attempt `task-323-attempt-1-37e3b4c661bd`，
  `freeform/fresh`）确认首个工具为 `sleep 90`，在 sleep 期间断开 `bridge`，并让 sleep 结束后的
  Provider 请求在断网状态等待；断网期间没有新的 Provider/SSE 事件，恢复网络后继续完成并收到
  `session.idle`。canonical seq `1–32`，2/2 tool、usage `154/23`、`322.211s`，
  `provider.retry=0`，唯一终态为 `run.completed`。runtime archive 为
  `072cfa946fa994769036ac351140c0a61e422f562776428b932cd656ad2ba320` / `10,267 B`，container
  已清理。

- 随后的隔离探索仍不追认进冻结 formal cohort：`#324/#325/#328`（OpenCode，沿用同一 Issue 的
  inherited `continue` session）因模型拒绝继承上下文中的 prompt，均无 tool；`#326` 在首个工具后
  断开 bridge 但仍以 5/5 tool 正常完成、没有 retry；`#327` 在 OpenCode 首个工具后将容器 namespace 的
  `eth0` 下线 75 秒，任务挂起后由外部取消，canonical 为 1/1 tool 的 `cancelled`；`#329` 虽为
  fresh OpenCode 且执行了 443 egress 阻断，但先遇到真实 `permission.asked` / `sandbox_error`，
  未形成可单独归因的 network failure，因此全部保留为探索性边界证据。
- 在旧 readiness generation `61`（verified at `2026-09-02 02:33:35.288051`，任务启动时已过期）
  上，`#330 / Issue #97`（OpenCode，Bundle `146`，attempt `task-330-attempt-1-b21f5c9efb53`）
  和 `#331 / Issue #93`（Pi，Bundle `147`，attempt `task-331-attempt-1-3fe240005be8`）改用首次
  `tool.completed` 后的一次性容器 namespace `OUTPUT tcp/443 REJECT`。#330 为 1/1 tool、seq
  `1–28`，5 次 `provider.retry`（全部 `engine_error`），最终 `harness.failed(engine_error)` →
  `run.failed(engine_error)`，archive `9604a0dbd5780f3c7cc09b9f7820a0e128bfe351e99d9b819b79e6becf5de6a0` /
  `8,476 B`；#331 为 2/2 tool、seq `1–51`，3 次 `provider.retry`（全部 `engine_error`），最终同类
  `engine_error` failure，archive `ba8ecac03099059fc073d59024ed23353234c314011ca03d866b6e495fc71a70` /
  `7,782 B`。#330 的观察器曾错误地重复开启一次短窗口；两项因 readiness 已过期不作为正式 canary，
  但保留为真实网络错误分类证据。
- 重新 Verify 后，Profile 4 readiness generation `64`（verified at `2026-09-02 04:08:33.825663`）
  的有效窗口内完成了正式 network interruption re-probe。Pi `#334 / Issue #93` 使用 Bundle `150`
  （digest `9ce9e05fee17e176caddf730279d81db232350fbe87b6fcdc7e47979388914e7`）、attempt
  `task-334-attempt-1-84a1c86de323`、`freeform/fresh`，耗时 `138.222s`；首次工具完成后施加一次
  容器 namespace 443 egress REJECT，canonical seq `1–52`、4/4 tool，随后 3 次
  `provider.retry`（seq `44–46`，均 `failure_kind=engine_error`），唯一终态为
  `harness.failed(engine_error: Connection error.)` → `worker.finalization(exit_code=1,diff=0/0)`
  → `run.failed(engine_error)`，无 commit/delivery；archive
  `9383afe0713cedcaa3b7018eaa318c4e4be7e5656c4181b41dd53ffc6a7533c2` / `12,296 B`。
  OpenCode `#335 / Issue #96` 使用 Bundle `151`（digest
  `192911896de9f68de75bbb1ade2b5ef1802d28577e96e7550f83dea0be1057a2`）、attempt
  `task-335-attempt-1-22384655ba76`、`freeform/fresh`，耗时 `233.849s`；同样在首个工具后施加
  443 egress REJECT，canonical seq `1–232`、9/9 tool，阻断窗口内出现 5 次 `provider.retry`
  （seq `17/19/21/23/25`，全部 `engine_error`），窗口结束后继续执行并以唯一
  `harness.completed` → `worker.finalization(exit_code=0,diff=0/0)` → `run.completed` 收敛，
  usage `664/335`（input/output），无 commit/delivery；archive
  `7e471120007c5e2b6db31bab82e6d07fab130b35487cfa1a4890f826368cb285` / `35,904 B`。两项 Bundle
  manifest 都固定记录 generation `64` 和 Kit `0.6.11`；目标 Worker container 已清理，当前队列为空。

四次 bridge 探索本身仍只证明恢复后任务可继续或安全收敛；#330/#331 首次形成了真实 egress 阻断后的
`engine_error` retry，但因 readiness 过期不作正式 canary；#334/#335 则在有效 generation `64`
窗口内形成了两种 Harness 的 raw/canonical retry 与终态证据。因此 Scenario 14 的 network
interruption 子分支现可接受，不能与既有 TLS/protocol 样本混写。

因此场景 14 登记为 `pass`：invalid-session 分支保留 OpenCode 的 engine-level session-not-found 与
Pi 的 adapter-side protocol error；network interruption 分支由 #334/#335 的有效 readiness
canary 闭合。两种 Harness 的 failure taxonomy、唯一 terminal、archive 和 Worker 清理均符合预期，
不能合并成同一错误字符串，也不能把既有 TLS/protocol 样本改写为本场景证据。

### Scenario 15 longest-context

场景 15 的验收是保留长输入/多轮只读任务的 usage、工具量、compaction 边界、唯一 terminal 和 0/0
delivery。首次独立 probe 为 `#271 / Issue #79`（OpenCode，attempt
`task-271-attempt-1-b93c2e993401`）和 `#272 / Issue #78`（Pi，attempt
`task-272-attempt-1-e5cbd9677abe`）：两边均 `run.completed`、delivery/finalization 0/0；#271 为
239.999s、5/5 tool、in 42 / cached 10,167 / out 3,437、seq `1–156`，archive
`38b343f9ff6d72407e75b152d7c1784b1df935d52ececf46eddf8de0790f0cfc` / `43,447 B`；#272 为
286.319s、2/2 tool、in 1,380 / cached 2,090 / out 3,831、seq `1–1724`，archive
`8ae0e8a97feb96f4f66d229de27588c44f6d5b6b6ae70bbe4a7e573fe8c5e8a3` / `119,938 B`。首次 probe 的
50-call 指令没有被模型完整执行，且没有 `context.compacted`，所以不单独作为正式阈值通过。

随后在独立 Issue 上用长输入和 `Implementation + require_changes=false + fresh` 重跑：OpenCode
`#273 / Issue #81`（attempt `task-273-attempt-1-f2198b783d53`）为 281.968s、21/21 tool、1 次
`provider.retry`、in 161 / cached 20,822 / out 908、seq `1–165`，archive
`bb0a542e5be434b5dc5c0e0b2fa6749f7dfdbdf6f551954ae20b99366137f0f6` / `37,704 B`；Pi
`#274 / Issue #80`（attempt `task-274-attempt-1-8a6a40024905`）为 191.327s、24/24 tool、in 34 /
cached 18,006 / out 1,363、seq `1–265`，archive
`ff52d9011e5deed247b2e387478e74a71badee792363f265da3b63773cb78d50` / `54,696 B`。两边均有
`harness.completed` → `delivery.completed` → `worker.finalization(exit_code=0,diff=0/0)` → 唯一
`run.completed`，container 已清理；重跑仍没有 `context.compacted`，该事实作为 compaction 边界
`not_triggered` 记录，而不是伪造事件。因此场景 15 以长任务 usage/性能和只读交付验收通过，
compaction 事件本身仍只由场景 11 负责。

### Scenario 16 multi-file refactor

固定验收为在小型 fixture 中只交付 `r3_s16.py` 与 `r3_s16_test.py`，实现 `normalize_pair`，测试通过，
并且 Git delivery 可追溯。Pi `#258 / Issue #69`（Bundle 134，attempt
`task-258-attempt-1-a0e5d4cf952d`）耗时 136.028s，9/9 tool，seq `1–122`，in 53 / cached 4,698 /
out 335，commit `bca2afdef31cc48cfaba9c1af0cbc977d95d1b77`，archive
`47d596a754a5303b23aa97769601108c8cbfac3520a8dc1d67ff1085caecef72` / `26,551 B`。OpenCode
`#259 / Issue #70`（Bundle 133，attempt `task-259-attempt-1-a3d4ab86e61a`）耗时 196.349s，11/11
tool，seq `1–269`，in 77 / cached 11,040 / out 371，commit
`d573243bc103b8336d7c5d9edbce89463c87b163`，archive
`d5ba0363b41cbce14b69b57abee9a4148621d0521d840a5c997e7d2d18801957` / `41,822 B`。两边均有
`harness.completed`、delivery、`worker.finalization(exit_code=0)` 和唯一 `run.completed`；模型在
Worker finalization 前已完成 commit，所以公共 finalization 的 diff 均为 0/0，commit SHA 以
delivery/finalization canonical payload 为准。人工验收确认两文件、测试和无 Python cache，场景 16
登记为 `pass`。

### Scenario 17 single-file bug fix

该场景采用 seed → fix/recovery lineages，验收只允许修复 `r3_s17.py` 的周边空白解析 bug，并保留所有
失败样本。Pi seed `#262 / Issue #73`（attempt `task-262-attempt-1-9f66f720164c`）耗时 215.669s，
18/18 tool，seq `1–843`，in 90 / cached 8,322 / out 477，commit
`9cf57ccb191c740871f47db67f69121bec4bf723`，archive
`cb4e064ba32f4e34d1ab3bd0a20fc0142ad1e4d3a31fe3288c27e1e3661425a3` / `86,938 B`；Pi fix
`#265 / Issue #73`（attempt `task-265-attempt-1-324cfd345594`）耗时 179.233s，20/20 tool，seq
`1–507`，in 206 / cached 5,723 / out 392，commit `ad238760fb06d405098570c58b7214fc1b2b3b08`，
archive `f6ef00baf67620bb39ba47fe23bb50b4331131fbb5391ccea58af35d95ad70a9` / `51,513 B`。

OpenCode seed `#263 / Issue #74`（attempt `task-263-attempt-1-94f5d6ee80ba`）有 18/18 tool、seq
`1–530`，耗时 244.452s，in 190 / cached 13,489 / out 277，archive
`8146af37792ae56664a08e440e1d1cf9be43f7f53eea550f8aa43e1983f8f092` / `73,758 B`；OpenCode 首轮
fix `#264`（attempt `task-264-attempt-1-a066e6dc0fac`）有 10/9 tool start/complete、seq `1–197`，
耗时 169.260s，archive `877c8f1ef2502c0d0f7443a02a969368334efda6846b16a0c68d6908c88a072c` /
`36,667 B`。两者均以唯一 `harness.failed(protocol_error: OpenCode protocol failure: session.idle
with active tool parts)` → `worker.finalization(exit_code=1)` → `run.failed` 收敛。随后 OpenCode
recovery `#268 / Issue #74`（attempt `task-268-attempt-1-4db54528a28f`）耗时 147.441s，7/7 tool，
seq `1–329`，in 119 / cached 9,292 / out 322，commit
`5148732cc90766cb1c4b2a8a8b04b528d5ebaf92`，archive
`60277d482cf5cc2e13964cf5e5c5fbfbbcee69224d6b730ec238bb48857b5cf1` / `41,081 B`，完成同一
目标文件的修复、验证和 delivery。各任务的模型 commit 均使公共 finalization diff 为 0/0；最终只含
目标 fixture，场景 17 登记为 `pass`，#263/#264 的真实协议失败不删除也不改写。

### Scenario 18 pure analysis

固定验收为只读仓库并输出分析，不写入、commit 或 delivery。Pi `#260 / Issue #71`（attempt
`task-260-attempt-1-4c61d4e92eef`）耗时 244.734s，7/7 tool，seq `1–1159`，in 179 / cached 4,462 /
out 2,149，archive `8f7f57a0b3302af953ab63a8d9f14bbaf86b12ab21fac09fc378b610dd174245` /
`89,037 B`；OpenCode `#261 / Issue #72`（attempt `task-261-attempt-1-3a6e6c4ba23b`）耗时 249.124s，
14/14 tool，seq `1–858`，in 216 / cached 13,389 / out 1,702，archive
`cf4ff276453702bf9b095405839c84f4320bc88c4eee721a4da84397d762a350` / `89,640 B`。两边均有
`harness.completed`、`delivery.completed(commit_sha=null)`、`worker.finalization(diff=0/0)` 和唯一
`run.completed`，workspace clean，场景 18 登记为 `pass`。

### Scenario 19 failure followed by public delivery

本轮新增一组独立的、两种 Harness 均可比的 failure → public delivery lineage，不复用场景 11、17
或 20 的 Issue。两条首轮任务都先产生了真实 failure 证据，随后在同一 Issue/lineage 上以新会话
追加 recovery，分别完成唯一 marker 文件的公共 Git delivery。

- Pi 首轮 `#277 / Issue #82` 使用 Bundle `134`、attempt `task-277-attempt-1-8d4e17c4aac7`、
  `execute/continue`，耗时 `232.491s`，usage in/cached/out/reasoning `34/1,868/290/null`，
  canonical seq `1–36`，`tool.started(Bash: sleep 120)` → `tool.completed`，随后
  `harness.completed`；因首轮无变更，公共 delivery 在 seq 34 以 `delivery.failed(exit_code=1,
  commit_sha=null)` 收敛，seq 35 `worker.finalization(exit_code=1, diff=0/0)`，唯一
  `run.failed(failure.kind=engine_error)`。archive `6d7195468d3627e5187695acc738ea549bf1ed7ba54a550338845a002b9b113c`
  / `7,582 B`，TaskLog 4 raw chunks / 2,369 B，MR !78 无 commit；该真实 delivery failure 保留为
  lineage 的首轮失败样本。
- Pi recovery `#279 / Issue #82` 使用 Bundle `134`、attempt `task-279-attempt-1-0bb66d9284fb`、
  `execute/fresh`、output session `01a05d3d-aad9-7fe9-a3d7-17880da78406`，耗时 `133.059s`，
  usage `165/2,437/272/null`，5/5 tool，canonical seq `1–69`；`harness.completed` →
  `delivery.completed(exit_code=0, commit_sha=d1cfaa02ae3c59b016954edfdebda1e557c48547)` →
  `worker.finalization(exit_code=0, diff=1/0)` → 唯一 `run.completed(success=true)`。TaskLog 6 raw
  chunks / 4,653 B，archive `7b9ffabeb16d52077420454732c21d0434f2d8d60f5bf6a0bce08809f079b97a` /
  `13,440 B`；MR !78 Changes 只有 `r3_s19_recovered_pi.txt`，内容为
  `r3-s19-recovered-pi-ok`，并由后续 `od -c` 工具输出确认尾换行。首次 `xxd` 探测因镜像未安装
  `xxd` 返回 tool error，但未污染 Harness/Task terminal；Worker container 已清理。
- OpenCode 首轮 `#278 / Issue #83` 使用 Bundle `133`、attempt `task-278-attempt-1-87be480ae0da`、
  `execute/continue`，耗时 `207.554s`，usage `0/0/0/0`，canonical seq `1–13`；在确认
  `codify-278-issue83`、attempt 和 `tool.started(Bash: sleep 120)` seq 9 后由 Task UI 取消，seq 11
  `harness.failed(kind=cancelled)`、seq 12 `worker.finalization(exit_code=143, diff=0/0)`、唯一
  `run.failed(status=cancelled, failure.kind=cancelled, exit_code=143)`。archive
  `4f0a45dff96c084b7eda3edec1b3269645b52a39c338c11d9929cc237071bbaa` / `7,552 B`，TaskLog 5 raw
  chunks / 2,991 B，MR !79 无 commit；container 已清理。
- OpenCode recovery `#280 / Issue #83` 使用 Bundle `133`、attempt `task-280-attempt-1-3d4376aadc22`、
  `execute/fresh`、output session `ses_fa2c1a394ffew7dkx4eEKA40et`，耗时 `135.217s`，usage
  `110/8,582/214/0`，4/4 tool，canonical seq `1–48`；`harness.completed` →
  `delivery.completed(exit_code=0, commit_sha=571aabc5f9150a4f58b133ae27249fe799bab807)` →
  `worker.finalization(exit_code=0, diff=1/0)` → 唯一 `run.completed(success=true)`。TaskLog 5 raw
  chunks / 4,707 B，archive `ef07fdbdaae1fc4a91c39d741a18039c4292c15eacc2be4ca0431718ed192f3c` /
  `15,078 B`；MR !79 Changes 只有 `r3_s19_recovered_opencode.txt`，内容为
  `r3-s19-recovered-opencode-ok`，TaskLog 中独立 shell 校验明确报告 content and trailing newline
  verified；container 已清理。

因此场景 19 登记为 `pass`：失败类型、canonical 唯一 terminal、同 Issue/lineage 顺序、两个公共
commit、单文件内容、archive/TaskLog 和 Worker 清理均可追溯；`#277` 的 delivery failure 与
`#278` 的稳定态取消均保留，不从历史删除或改写。

### Scenario 20 high-token generation

固定验收为生成三个各 80 行的确定性文件和 1,200+ 字报告，并记录 usage、耗时及 delivery。Pi
`#266 / Issue #75`（attempt `task-266-attempt-1-812f7d9370f4`）耗时 184.220s，9/9 tool，seq
`1–188`，in 375 / cached 6,366 / out 2,391，commit
`7b1cc8f71744ce1a403d4ed640390eb60070b0dd`，archive
`8081861c85b5b5cfce122454839ce9e1583185997824d251ad1aa62d134803fc` / `44,397 B`；模型已先 commit，
因此公共 finalization diff 为 0/0，但三文件 80/80/80 行和报告验收成立。

OpenCode 首轮 `#267 / Issue #76`（attempt `task-267-attempt-1-13335d83c06d`）耗时 211.601s，
22/22 tool，seq `1–226`，in 194 / cached 14,509 / out 3,271，archive
`7fb7f8c0e7577b583090d167eaaecdf25c41f87a6ff0522e33cd152235e3ec4f` / `61,461 B`，以
`protocol_error: session.idle with active tool parts` 失败；recovery `#269 / Issue #76` 耗时 162.580s，
6/6 tool，seq `1–446`，in 338 / cached 9,152 / out 962，archive
`992da0a78111a7dc75ee745aab1a536879f8b7c96ff4c0a3819fc835bef879fb` / `47,152 B`，虽有
`harness.completed` 和三文件/报告验收，但因已有 commit `1acf2a50d3d593cee99b9c6141d79d19f1de186f` 不再有待交付 diff，公共
`delivery.failed`、`worker.finalization(exit_code=1)` 和 `run.failed`；该失败链路保留。

为避免把已有分支 commit 当成公共 delivery，另建独立 Issue 77 做最终 OpenCode probe：`#270`（attempt
`task-270-attempt-1-643bf245c509`）耗时 234.985s，5/5 tool，seq `1–1233`，in 74 / cached 9,373 /
out 2,906，`harness.completed` → `delivery.completed(exit_code=0, commit_sha=0f43822cf62ce6d4afedf1a6883d3786f201ed1a)`
→ `worker.finalization(diff=240/0)` → 唯一 `run.completed`，archive
`794f60109b457a0f17ba95edb160965942cd221bb087b2b062b08fc61e794fe2` / `109,974 B`，container
已清理。人工验收确认三个 80 行文件、1,200+ 字报告和只包含目标变更，场景 20 登记为 `pass`，
`#267/#269` 不从历史中删除。

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

## Current statistical rollup

本节只计算下方 Frozen 20 与 Execution ledger 中的冻结/配对记录；`#317/#318/#319` 等关联诊断不回填为
formal benchmark 样本。场景级 `pass` 代表人工验收、canonical terminal、archive、delivery 和清理均符合
该场景语义，不等同于单纯的 `Task.status=completed`。

| 口径 | 当前结果 | 说明 |
|---|---:|---|
| 冻结场景 | 20 | 场景定义不变；需要多阶段 lineage 的场景仍只计一个场景样本 |
| 已有 formal Pi/OpenCode pair 的场景 | 19/20 | `#1–12`、`#14–20` 已有配对记录；场景 13 尚无可接受的 Provider 401 formal pair |
| 场景级 full `pass` | 18/20（90%） | `#1–11`、`#14–20` |
| 场景级 partial | 0/20 | 场景 14 的 invalid-session 与 network interruption 两个子分支均已闭合 |
| `not_triggered` | 1/20 | 场景 12 的 formal pair 均未自然触发 `provider.retry` |
| `blocked_external_fixture` | 1/20 | 场景 13 仍缺真实 Provider-side HTTP 401 fixture |

### Preliminary paired performance subset

为避免把取消、timeout、Provider retry/认证 fixture 和网络断线等控制语义混入普通工作量统计，先对场景
`#1–8`、`#15–20` 的 14 个配对样本做描述性汇总。每个场景取最终被人工接受的 terminal Task；`#8/#17/#19`
取其 continue/recovery 终态，不把整个 lineage 的探索性失败耗时重复相加。Processed tokens 定义为
`input + cached + output`，reasoning token 在这组样本中为 `null/0`。

| 指标 | Pi | OpenCode（当前较优兼容 Harness） | Pi 相对 OpenCode |
|---|---:|---:|---:|
| 配对终态人工验收 | 14/14 | 14/14 | — |
| 中位耗时 | 170.185s | 160.491s | +6.0% |
| 中位 processed tokens | 4,494.5 | 10,555.5 | -57.4% |

Pi representative Task 为 `#201,#202,#205,#207,#228,#223,#232,#239,#274,#258,#265,#260,#279,#266`；
OpenCode representative Task 为 `#200,#204,#206,#208,#231,#225,#233,#237,#273,#259,#268,#261,#280,#270`。
该子集没有出现“耗时和 Token 同时恶化超过 25%”，但它不是完整 R3 gate 结果：场景 12 与场景 13
仍未闭合，故不能据此关闭 R3。

## Frozen 20 scenarios

Task ID 留空表示尚未执行；正式执行过程中只追加结果，不改变场景定义或删除失败样本。

| # | 场景与固定验收 | Pi Task(s) / Issue | OpenCode Task(s) / Issue | 状态 |
|---:|---|---|---|---|
| 1 | `plan` 模式：只读检查并返回计划，无代码变更、无 Git delivery | `#201 / Issue #25`；Bundle `123`；attempt `task-201-attempt-1-577ce4a8347c`；`plan/fresh`；output session `01a05b5c-a43b-7525-a72e-88834b361e25`；522.924s；in 101 / cached 6,096 / out 1,610 / reasoning null；11 对 tool 事件；seq 1–935，唯一 terminal `run.completed(success=true)`；`provider.retry` seq 56 (`engine_error`，随后成功)；0/0，commit null；archive `1724105c28854e501af9f0f012a07214d37830efda320925cf276570ea5629ce` / 75,289 B；container 已清理 | `#200 / Issue #24`；Bundle `124`；attempt `task-200-attempt-1-8d29ba0b9e28`；`plan/fresh`；output session `ses_fa4ac31ecffe1UmB3S3VmA3oEU`；220.785s；in 101 / cached 10,417 / out 1,837 / reasoning 0；7 对 tool 事件；seq 1–905，唯一 terminal `run.completed(success=true)`；0/0，commit null；archive `cc4df4e4d68e9dd32fbf73cc3e796b7735688fa0c3af5038cbdc16b8d91c0fdb` / 85,968 B；container 已清理 | pass（两边均通过只读验收，无 Git commit/diff；Issue 上的初始 MR 是 plan/execute 共用的 pre-run tracking 生命周期，不计为 commit delivery；Pi 记录 1 次真实 retry） |
| 2 | `execute` 模式：完成一个最小、可验收的单文件变更并 delivery | `#202 / Issue #26`；Bundle `123`；attempt `task-202-attempt-1-63cdebe66ea8`；`execute/fresh`；output session `01a05b6b-28ea-7529-a6cb-8c6feb0d8943`；443.414s；in 95 / cached 2,638 / out 199 / reasoning null；7 对 tool 事件；seq 1–194，唯一 terminal `run.completed(success=true)`；`provider.retry` seq 45 (`engine_error`，随后成功)；1/0，commit `2c110cb57762415faf19b224f097e5f295c5742a`；archive `aff00463349bd022dc16adb36963c741ed9d86d0d73b8304118ae0809675a7f5` / 19,482 B；MR !22 `in_review`；container 已清理 | `#204 / Issue #28`（首次尝试 `#203 / Issue #27` 停滞取消，失败证据保留且不计入成功配对）；Bundle `124`；attempt `task-204-attempt-1-db897b7cbd8b`；`execute/fresh`；output session `ses_fa4878450ffepy3SfdOdvqOc5Q`；154.833s；in 114 / cached 8,684 / out 159 / reasoning 0；7 对 tool 事件；seq 1–143，唯一 terminal `run.completed(success=true)`；1/0，commit `c926b7ecb8a9f5331602b7b9c78dabdd8f868a3b`；archive `d489331989004d62fbe8ca03abf1da5660388c5d9f55a28826cd18a8f4ac9339` / 22,931 B；MR !24 `in_review`；container 已清理 | pass（两边均创建唯一 `r3-s02-marker.txt` 并完成单文件验收；Pi 有 1 次真实 `provider.retry`；Issue 上的初始 MR 是 plan/execute 共用的 pre-run tracking 生命周期，不计为 Git commit delivery；#203 的停滞取消不从失败记录中删除） |
| 3 | `freeform` 模式：完成一个最小、可验收的单文件变更并 delivery | `#205 / Issue #29`；Bundle `123`；attempt `task-205-attempt-1-c7362711a113`；`freeform/fresh`；output session `01a05b86-3118-78b3-ba66-c19d931ec050`；111.955s；in 149 / cached 1,713 / out 78 / reasoning null；3 对 tool 事件；seq 1–68，唯一 terminal `run.completed(success=true)`；1/0，commit `116ab830ebeb7646b4141f26885ae2c2c79707f4`；archive `21dd54c69bd989872e77693ad6343f4e16705ff1fcabb173c33f07449886aae3` / 8,988 B；MR !25 `in_review`；container 已清理 | `#206 / Issue #30`；Bundle `124`；attempt `task-206-attempt-1-7ffd7bbe93e5`；`freeform/fresh`；output session `ses_fa4783e89ffeYzWQqnA8E0jzr9`；128.508s；in 134 / cached 8,044 / out 32 / reasoning 0；4 对 tool 事件；seq 1–54，唯一 terminal `run.completed(success=true)`；1/0，commit `6292751de16e27ed62230b9bf8b9aec310fd5972`；archive `bbb1b1e8768a513e7fe91de6bdb1def89820c8af5053d98dbb4c4a6edb93c6bf` / 13,015 B；MR !26 `in_review`；container 已清理 | pass（两边均创建并验证唯一 `r3-s03-marker.txt`，内容为 `r3-s03-ok`，无其他文件修改，并成功 delivery） |
| 4 | 工具成功：执行只读 shell 检查后完成标记文件；tool start/complete 成对出现 | `#207 / Issue #31`；Bundle `123`；attempt `task-207-attempt-1-d9d2c17503c0`；`execute/fresh`；output session `01a05b8f-0f1b-76e1-867d-0c79ba6048db`；167.550s；in 228 / cached 3,149 / out 526 / reasoning null；8 对 tool 事件；seq 1–306，唯一 terminal `run.completed(success=true)`；1/0，commit `0eeaae5551d76a83ed1e15e817525cd564ddd8f0`；archive `d6f7621e3937f4e02b83ed3f6056862391ba88c2b887b90fc986956b1d1c2fc3` / 29,347 B；MR !27 `in_review`；container 已清理 | `#208 / Issue #32`；Bundle `124`；attempt `task-208-attempt-1-8d9d3a7d9196`；`execute/fresh`；output session `ses_fa47002eeffeD1G0szjhjLV1OE`；166.149s；in 133 / cached 10,512 / out 314 / reasoning 0；10 对 tool 事件；seq 1–283，唯一 terminal `run.completed(success=true)`；1/0，commit `a98fccffdef1ec1834a0969487deaab45ba89c5d`；archive `f986a96382e00e2c14d886d22806c46c76e75f11c71029720e820e5b0d409089` / 39,605 B；MR !28 `in_review`；container 已清理 | pass（两边均先完成成功的只读 shell 检查，再创建并验证唯一 `r3-s04-marker.txt`，并成功 delivery；#207/#208 的 tool start/complete 分别为 8/8、10/10，期间的无害路径探测错误保留在 TaskLog，不影响 terminal） |
| 5 | 工具失败：执行一个明确预期失败的无害命令，继续完成标记文件；失败不污染 terminal | `#228 / Issue #48`；Bundle `132`；attempt `task-228-attempt-1-11cefcad3fda`；`execute/fresh`；seq `1–346`；7/7 tool；archive 31,543 B；commit `01ae03e…`；MR !44 | `#231 / Issue #50`；Bundle `133`；attempt `task-231-attempt-1-1a8a35382d1b`；`execute/fresh`；seq `1–170`；4/4 tool；archive 23,736 B；commit `ef71698…`；MR !46 | pass（严格 standalone exit 7 均有 canonical `error=true`，之后继续写入并交付唯一 marker；#229 的 `exit_code=7,error=false` 缺陷及 #226/#227 掩盖退出样本保留） |
| 6 | 测试修复：建立/识别一个失败测试，修复后重新运行并交付通过结果 | `#223 / Issue #44`；Bundle `129`；attempt `task-223-attempt-1-d824ebd9ad50`；`execute/fresh`；seq `1–216`；15/15 tool；archive 43,055 B；commit `aa78dec…`；MR !40 | `#225 / Issue #45`；首轮 `#224` 为保留的 OpenCode `permission.asked` / `sandbox_error` 失败（Bundle `130`，seq `1–122`），retry Bundle `131`；attempt `task-225-attempt-1-7aeae9f16c25`；`execute/fresh`；seq `1–375`；15/15 tool；archive 57,684 B；commit `7888ef5…`；MR !41 ready | pass（两边均记录初始失败与同一测试成功重跑；最终只含两个 fixture 文件且无 Python cache；#224 失败证据保留） |
| 7 | 无改动：`execute` + `require_changes=false`，只读检查，完成且无 commit/diff | `#232 / Issue #51`；Bundle `134`；attempt `task-232-attempt-1-434e1c03d681`；`execute/fresh`；seq `1–46`；2/2 tool；archive 14,384 B；commit null；MR !47 | `#233 / Issue #52`；Bundle `133`；attempt `task-233-attempt-1-c479e0c4e54a`；`execute/fresh`；seq `1–172`；4/4 tool；archive 27,182 B；commit null；MR !48 | pass（两边只读验收通过；`require_changes=false`，canonical terminal 成功，delivery/finalization 均为 0/0，远端 workspace clean） |
| 8 | resume/continue：fresh seed 后在同一 Issue/lineage continue，两个 Task 均可追溯 | `#238 → #239 / Issue #55`；Bundle `134`；fresh/continue；seq `1–375` / `1–304`；11/11、8/8 tool；archive 35,026 B / 28,552 B；commits `5bb6f09…` / `344f3e79…`；MR !51 | `#236 → #237 / Issue #54`；Bundle `133`；fresh/continue；seq `1–145` / `1–133`；5/5、4/4 tool；archive 22,667 B / 20,741 B；commits `94fc3a7…` / `05432842…`；MR !50 | pass（两边均同 Issue/lineage 完成 fresh→continue；input session 可追溯，最终各只含 seed + continuation 文件，workspace clean） |
| 9 | 稳定态取消：确认 attempt/container/tool 已初始化后取消；`cancelled`、SIGTERM、清理 | `#240 / Issue #56`；Bundle `134`；attempt `task-240-attempt-1-093430781533`；`execute/fresh`；require_changes=true；seq `1–19`；tool started 后取消；archive 5,114 B；无 commit | 历史 `#241 → #242 → #243`、`#244` 首工具前 protocol failure 保留；最终 `#275 / Issue #57`；seq `1–12`，tool started 后取消；archive 7,148 B；无 commit | pass（#240/#275 均满足稳定态取消、exit 143、唯一 terminal 和清理） |
| 10 | timeout/SIGKILL：临时使用最小可保存 timeout，任务阻塞并由 runner 收敛，恢复配置 | `#245 / Issue #59`；Bundle `134`；attempt `task-245-attempt-1-078f64dfad02`；`execute/fresh`；`require_changes=true`；seq `1–22`，`tool.started(sleep 180)` → `harness.failed(timeout)` → `worker.finalization(exit 143)` → `run.failed(timeout)`；archive 5,447 B；无 commit | `#246 / Issue #60`；Bundle `133`；attempt `task-246-attempt-1-2d40ba54e123`；`execute/fresh`；`require_changes=true`；seq `1–18`，`tool.started(sleep 180)` → `harness.failed(timeout)` → `worker.finalization(exit 143)` → `run.failed(timeout)`；archive 7,682 B；无 commit | pass（两边均由临时 60s runner timeout 真实收敛，配置恢复为 1800s，container/workspace 清理成立） |
| 11 | context compaction：长上下文任务必须产生 `context.compacted`，其后仍有唯一 terminal | `#251 → #252 / Issue #63`；Bundle `134`；5 次 compaction，`#251` seq `1–929` 失败后 `#252` 完成 recovery delivery；archives `1,778,253 / 35,934 B`；最终 commit `38f3a610…` | `#253 + #276 / Issue #64`；#276 37/37 tool、seq `1–307`、3 次 retry、cached 436,138、无 compaction、engine_error；追加 `#293/#295` 成功 delivery 但无 compaction，`#298/#300` native POST 为 `503`，`#302` watcher 超时取消，`#303/#304` idle active-tool `protocol_error`，`#305/#306` clean-idle watcher 未捕获状态，`#307/#308` Task/Host watcher 均未形成 route/event 闭环；追加 `#309/#310`（Provider `7` / Profile `4` / Bundle `138`，6/6 与 82/82 tool，均无 compaction）；追加 `#313` continuation timeout、`#314` legacy route 短任务 compaction、`#315` Bundle `139` 长上下文 37/37 tool 和 3 次 canonical compaction；archives 205,787 / 8,979 / 18,230 / 117,822 B；无 commit | pass（Pi compaction/recovery 与 OpenCode 长上下文 legacy compatibility route 均有 raw/canonical compaction 和唯一 terminal；V2 native compact `503` 保留为上游能力边界） |
| 12 | rate limit：使用已有受限 Provider，记录 `provider.retry` 与 `rate_limited` 分类 | `#254 / Issue #65`、`#256 / Issue #67`；Bundle `134`；13/13、26/26 tool；seq `1–427` / `1–592`；archives `44,906 / 57,578 B`；commits `d10ab625…` / `f16e80eb…`；关联当前 Provider 7/Pi 控制样本 `#318 / Issue #92`，Bundle `142`，seq `1–72`，无 retry，archive `8,190 B` | `#255 / Issue #66`、`#257 / Issue #68`；Bundle `133`；8/8、26/26 tool；seq `1–318` / `1–309`；archives `42,300 / 49,189 B`；commits `29a3181a…` / `7b63cdc5…`；关联真实诊断 `#317` 为 Provider 9 / Bundle `141` | not_triggered（正式 probe 与 #318 均无 retry；#250/#251/#317 的真实 `rate_limited` 只作为关联诊断保留） |
| 13 | authentication failure：只接受真实 401/`authentication_error`；无 401 fixture 不得伪造 | 关联真实诊断 `#319 / Issue #92`：Provider 6 / Pi，Bundle `143`，`rate_limited` / 429，无 401 | `#296/#310` 的无凭据 Server Basic Auth `401` 不计入 Provider 401；历史 `#150/#151` 的 `authentication_error` 实为 `404` HTML；`#316` 为 Provider 11 的真实 `engine_error` / certificate failure；`#317` 为 Provider 9 的真实 429；`#319` 为 Provider 6 的真实 429；均无 401，仍无专用 401 fixture | blocked_external_fixture |
| 14 | network/invalid session：真实断线或非法 Session，记录 retry/engine 或 invalid-session 分类 | `#289 / Issue #87`；Bundle `136`；`plan/continue`；attempt `task-289-attempt-1-b5cdfed0c915`；seq `1–4`；archive `2,788 B`；无 output session；container 已清理；有效 network re-probe `#334 / Issue #93`，Bundle `150`，attempt `task-334-attempt-1-84a1c86de323`，`freeform/fresh`，4/4 tool，seq `1–52`，3 次 `engine_error` retry，最终 `run.failed(engine_error)`，archive `12,296 B` | `#281 / Issue #84`；Bundle `133`；`plan/continue`；attempt `task-281-attempt-1-b8c96260cd74`；seq `1–4`；archive `2,835 B`；engine_error；无 output session；container 已清理；有效 network re-probe `#335 / Issue #96`，Bundle `151`，attempt `task-335-attempt-1-22384655ba76`，`freeform/fresh`，9/9 tool，seq `1–232`，5 次 `engine_error` retry 后 `run.completed`，archive `35,904 B` | pass（invalid-session 与 network interruption 均有有效 canonical taxonomy、唯一 terminal、archive 和清理；#320–#331 的 bridge/过期 readiness 探针保留为历史边界证据） |
| 15 | longest-context：长输入/多轮任务记录 usage、compaction 边界和完成/失败结果 | formal retry `#274 / Issue #80`；24/24 tool；seq `1–265`；191.327s；in 34 / cached 18,006 / out 1,363；archive 54,696 B | formal retry `#273 / Issue #81`；21/21 tool；seq `1–165`；281.968s；in 161 / cached 20,822 / out 908；1 retry；archive 37,704 B | pass（两边 0/0、唯一 `run.completed`；未触发 `context.compacted`，按边界事实记录） |
| 16 | 多文件重构：小型 fixture 的多文件一致性改造，测试、commit、push/MR | `#258 / Issue #69`；9/9 tool；seq `1–122`；commit `bca2afde…`；archive 26,551 B | `#259 / Issue #70`；11/11 tool；seq `1–269`；commit `d573243b…`；archive 41,822 B | pass（两边完成两文件测试和 delivery；模型先 commit，finalization diff 0/0） |
| 17 | 单文件 bug fix：只改目标文件，测试/验收通过并 delivery | `#262 → #265 / Issue #73`；seed/fix；18/18、20/20 tool；commits `9cf57ccb…` / `ad238760…` | `#263/#264 → #268 / Issue #74`；两次 protocol failure 后 recovery；7/7 tool；commit `5148732c…` | pass（最终只改目标文件并 delivery；原始 OpenCode failures 保留） |
| 18 | 纯分析：只读仓库并输出分析，无写入、commit 或 delivery | `#260 / Issue #71`；7/7 tool；seq `1–1159`；archive 89,037 B；commit null | `#261 / Issue #72`；14/14 tool；seq `1–858`；archive 89,640 B；commit null | pass（两边 0/0、clean workspace、唯一 `run.completed`） |
| 19 | 失败后公共 delivery：第一轮保留失败证据，后续修复/重试成功 delivery，顺序可追溯 | `#277 → #279 / Issue #82`；Pi `#277` delivery failure、`#279` 5/5 tool、seq `1–69`、commit `d1cfaa02…`、archive `7,582 / 13,440 B` | `#278 → #280 / Issue #83`；OpenCode `#278` 稳定态取消、`#280` 4/4 tool、seq `1–48`、commit `571aabc5…`、archive `7,552 / 15,078 B` | pass（独立 Issue/lineage；两边 failure→public delivery 顺序、单文件内容和清理均成立） |
| 20 | 高 token 生成：明确的长输出/多文件生成，记录 usage、耗时和 delivery | `#266 / Issue #75`；9/9 tool；seq `1–188`；in 375 / cached 6,366 / out 2,391；commit `7b1cc8f7…` | `#267/#269 / Issue #76` 保留失败；最终 `#270 / Issue #77`；5/5 tool；seq `1–1233`；in 74 / cached 9,373 / out 2,906；commit `0f43822c…` | pass（独立 OpenCode #270 公共 delivery 成功；#267/#269 failure chain 保留） |

## Execution ledger

下表只登记已经完成或明确终止的场景摘要；详细 raw archive、TaskLog、canonical event 和 UI 证据按
Task ID 追溯，不把凭据写入文档。

> Scenario 11 行的 OpenCode 原始 cohort 摘要保留了 `#253/#276` 的 TLS failure 记录；后续正式追加的
> `#293/#294/#295` 结果以本文件的 Scenario 11 章节为准：TLS error 未再复现，但当时没有结构化
> `context.compacted`，因此当时状态为 `blocked_external_fixture`；最新 #315 已满足硬条件，当前状态见
> 下方更新。

> 随后的受控 legacy compatibility route 已在 `#314/#315` 的 Bridge 内认证调用中产生 raw/canonical
> compaction；其中 `#315` 是满足长上下文硬条件的最新样本。因此 Scenario 11 当前状态为 `pass`；
> `#253/#276/#293/#294/#295` 的历史 blocker 与 `#313` timeout 继续保留，不被新样本覆盖。

| Pair | Pi | OpenCode | Same prompt/Provider | Result / note |
|---:|---|---|---|---|
| 1 | `#201 / Issue #25` — completed；Pi Bundle `123`；0/0；522.924s；in 101 / cached 6,096 / out 1,610；11 对 tool；seq 1–935；archive 75,289 B；MR !21 无 commit | `#200 / Issue #24` — completed；OpenCode Bundle `124`；0/0；220.785s；in 101 / cached 10,417 / out 1,837；7 对 tool；seq 1–905；archive 85,968 B；MR !20 无 commit | frozen Provider `7 / openrouter-free`, `plan/fresh`, same semantic prompt | pass（只读结果和无变更验收通过；Pi 有 1 次 `provider.retry` 后成功；MR 为 pre-run tracking artifact） |
| 2 | `#202 / Issue #26` — completed；Pi Bundle `123`；1/0；443.414s；in 95 / cached 2,638 / out 199；7 对 tool；seq 1–194；archive 19,482 B；MR !22；commit `2c110cb5…` | `#204 / Issue #28` — completed；OpenCode Bundle `124`；1/0；154.833s；in 114 / cached 8,684 / out 159；7 对 tool；seq 1–143；archive 22,931 B；MR !24；commit `c926b7ec…`；`#203 / Issue #27` 为保留的首次停滞取消失败 | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic marker prompt | pass（#202/#204 均为唯一 marker 文件并成功 delivery；#202 有 1 次 `provider.retry`；#203 canonical 失败链路保留，不计入成功配对） |
| 3 | `#205 / Issue #29` — completed；Pi Bundle `123`；1/0；111.955s；in 149 / cached 1,713 / out 78；3 对 tool；seq 1–68；archive 8,988 B；MR !25；commit `116ab830…` | `#206 / Issue #30` — completed；OpenCode Bundle `124`；1/0；128.508s；in 134 / cached 8,044 / out 32；4 对 tool；seq 1–54；archive 13,015 B；MR !26；commit `6292751d…` | frozen Provider `7 / openrouter-free`, `freeform/fresh`, same semantic marker prompt | pass（两边均完成唯一 marker 文件验收和 delivery） |
| 4 | `#207 / Issue #31` — completed；Pi Bundle `123`；1/0；167.550s；in 228 / cached 3,149 / out 526；8 对 tool（8/8）；seq 1–306；archive 29,347 B；MR !27；commit `0eeaae55…` | `#208 / Issue #32` — completed；OpenCode Bundle `124`；1/0；166.149s；in 133 / cached 10,512 / out 314；10 对 tool（10/10）；seq 1–283；archive 39,605 B；MR !28；commit `a98fccff…` | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic tool-success prompt | pass（两边都有成功只读检查和 marker delivery；观察到的路径探测错误不影响 tool pairing/terminal，详情见 TaskLog） |
| 5 | `#228 / Issue #48` — completed；Pi Bundle `132`；1/0；172.820s；7/7 tool；seq 1–346；archive 31,543 B；MR !44；commit `01ae03e…` | `#231 / Issue #50` — completed；OpenCode Bundle `133`；1/0；144.059s；4/4 tool；seq 1–170；archive 23,736 B；MR !46；commit `ef71698…` | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic tool-failure prompt | pass（两边 standalone `exit 7` 均有 canonical `error=true`，随后继续完成 marker delivery；#226/#227 掩盖退出样本和 #229 的 OpenCode 分类缺陷均保留） |
| 6 | `#223 / Issue #44` — completed；Pi Bundle `129`；1/0；160.856s；in 51 / cached 8,081 / out 501；15 对 tool（15/15）；seq 1–216；archive 43,055 B；MR !40；commit `aa78dec…` | `#225 / Issue #45` — completed；OpenCode Bundle `131`；1/0；173.361s；in 176 / cached 13,188 / out 415；15 对 tool（15/15）；seq 1–375；archive 57,684 B；MR !41；commit `7888ef5…`；`#224` 为保留的首轮 sandbox_error 失败 | frozen Provider `7 / openrouter-free`, `execute/fresh`, same semantic test-repair prompt | pass（failure→delivery 顺序可追溯；两边最终均只含两个 fixture 文件；OpenCode 的 `/tmp/**` 权限修复和交付前 Python cache 清理均有真实 Host 证据） |
| 7 | `#232 / Issue #51` — completed；Pi Bundle `134`；0/0；108.496s；2 对 tool；seq 1–46；archive 14,384 B；MR !47 无 commit | `#233 / Issue #52` — completed；OpenCode Bundle `133`；0/0；138.661s；4 对 tool；seq 1–172；archive 27,182 B；MR !48 无 commit | frozen Provider `7 / openrouter-free`, `execute/fresh`, `require_changes=false` | pass（只读验收、canonical terminal、0/0 delivery/finalization 和 clean workspace 均成立） |
| 8 | `#238 → #239 / Issue #55` — completed；Pi Bundle `134`；fresh/continue；seq 1–375 / 1–304；archive 35,026 / 28,552 B；commits `5bb6f09…` / `344f3e79…` | `#236 → #237 / Issue #54` — completed；OpenCode Bundle `133`；fresh/continue；seq 1–145 / 1–133；archive 22,667 / 20,741 B；commits `94fc3a7…` / `05432842…` | frozen Provider `7 / openrouter-free`, same Issue/lineage, `require_changes=true` | pass（session lineage、seed/continuation delivery 和 clean workspace 均成立） |
| 9 | `#240 / Issue #56` — cancelled；Pi Bundle `134`；`execute/fresh`；150.515s；seq 1–19；`tool.started` 后取消；archive 5,114 B；无 commit；container 已清理 | 历史 `#241/#242/#243 / Issue #57` 与 `#244 / Issue #58` 首工具前 protocol failure 保留；最终 `#275 / Issue #57` — cancelled；157.670s；seq 1–12；`tool.started` 后取消；archive 7,148 B；无 commit；container 已清理 | frozen Provider `7 / openrouter-free`, `execute/fresh`, `require_changes=true`, same cancellation prompt | pass（#240/#275 均稳定态取消并以 exit 143/唯一 terminal 收敛） |
| 10 | `#245 / Issue #59` — failed(timeout)；Pi Bundle `134`；1,713/128/47；144.750s；1/1 tool；seq 1–22；archive 5,447 B；无 commit；container 已清理 | `#246 / Issue #60` — failed(timeout)；OpenCode Bundle `133`；0/0/0；144.617s；1/1 tool；seq 1–18；archive 7,682 B；无 commit；container 已清理 | frozen Provider `7 / openrouter-free`, `execute/fresh`, `require_changes=true`, same `sleep 180` prompt；global timeout temporarily 60s then restored 1800s | pass（两边均在 tool started 后由 runner 以 timeout/exit 143 收敛，队列为空且配置已恢复） |
| 11 | `#251 → #252 / Issue #63` — compaction/失败→delivery recovery；Bundle `134`；#251 5 次 compaction、seq `1–929`、archive 1,778,253 B；#252 seq `1–305`、commit `38f3a610…`、archive 35,934 B | `#253 + #276 / Issue #64` — #276 37/37 tool、seq `1–307`、3 次 retry、cached 436,138、无 compaction；追加 `#293/#295` 成功 delivery 但无 compaction，`#298/#300` native POST 为 `503`，`#302` watcher 超时取消，`#303/#304` idle active-tool `protocol_error`，`#305/#306` clean-idle watcher timeout，`#307/#308` 未捕获 route 状态；archive 205,787 B；unknown certificate verification error；无 commit | pass（Pi compaction/recovery 与 OpenCode #315 长上下文 legacy route 均有 raw/canonical compaction 和唯一 terminal；V2 native compact 503 保留为上游能力边界） |
| 12 | `#254 / Issue #65` + `#256 / Issue #67` — completed；Bundle `134`；13/13、26/26 tool；seq `1–427` / `1–592`；archives 44,906 / 57,578 B；commits `d10ab625…` / `f16e80eb…` | `#255 / Issue #66` + `#257 / Issue #68` — completed；Bundle `133`；8/8、26/26 tool；seq `1–318` / `1–309`；archives 42,300 / 49,189 B；commits `29a3181a…` / `7b63cdc5…` | not_triggered（两轮正式 probe 无 `provider.retry`；#250/#251 的 rate_limited 不重复计入） |
| 13 | 关联诊断 `#319 / Issue #92`；Provider 6 / Pi；Bundle `143`；`rate_limited` / 429；无 401 | 无 formal task；`#296/#310` 的 401 是 Server Basic Auth，`#150/#151` 是 404 HTML，`#316` 是 certificate error，`#317` 是 Provider 9 的 429；仍无专用 401 fixture | frozen Provider metadata；不读取 secret | blocked_external_fixture |
| 14 | invalid-session `#289`；有效 network re-probe `#334 / Issue #93`，Bundle `150`，4/4 tool，seq `1–52`，3 次 `engine_error` retry，archive `12,296 B` | invalid-session `#281`；有效 network re-probe `#335 / Issue #96`，Bundle `151`，9/9 tool，seq `1–232`，5 次 `engine_error` retry 后完成，archive `35,904 B` | Provider `7 / openrouter-free`、Profile `4`；#334/#335 均绑定 readiness generation `64`，旧 bridge/过期 readiness 探针不计入 formal canary | pass（invalid-session 与 network interruption 子分支均闭合） |
| 15 | `#271/#272` 初次 probe；formal `#274 / Issue #80` — completed；24/24 tool；seq 1–265；0/0；archive 54,696 B；无 compaction | `#271/#272` 初次 probe；formal `#273 / Issue #81` — completed；21/21 tool；seq 1–165；1 retry；0/0；archive 37,704 B；无 compaction | frozen Provider `7 / openrouter-free`, long-input `Implementation/fresh`, `require_changes=false` | pass（usage/长任务边界记录完整；compaction `not_triggered`） |
| 16 | `#258 / Issue #69` — completed；9/9 tool；seq 1–122；136.028s；in 53 / cached 4,698 / out 335；archive 26,551 B；commit `bca2afde…` | `#259 / Issue #70` — completed；11/11 tool；seq 1–269；196.349s；in 77 / cached 11,040 / out 371；archive 41,822 B；commit `d573243b…` | frozen Provider `7 / openrouter-free`, same two-file refactor prompt | pass（两边 test/delivery 成立；finalization diff 0/0 因模型已先 commit） |
| 17 | `#262 → #265 / Issue #73` — seed/fix completed；archives 86,938 / 51,513 B；commits `9cf57ccb…` / `ad238760…` | `#263/#264 → #268 / Issue #74` — #263/#264 protocol failure，#268 completed；archives 73,758 / 36,667 / 41,081 B；commit `5148732c…` | frozen Provider `7 / openrouter-free`, same single-file bug fixture | pass（最终目标文件修复和 delivery 成立；原始 failures 保留） |
| 18 | `#260 / Issue #71` — completed；7/7 tool；seq 1–1159；244.734s；in 179 / cached 4,462 / out 2,149；archive 89,037 B；无 commit | `#261 / Issue #72` — completed；14/14 tool；seq 1–858；249.124s；in 216 / cached 13,389 / out 1,702；archive 89,640 B；无 commit | frozen Provider `7 / openrouter-free`, read-only analysis | pass（0/0、clean workspace、terminal/delivery/finalization 完整） |
| 19 | `#277 → #279 / Issue #82` — 首轮 delivery failure 保留；recovery completed；Pi Bundle `134`；5/5 tool；seq `1–69`；133.059s；in 165 / cached 2,437 / out 272；archives 7,582 / 13,440 B；MR !78；commit `d1cfaa02…` | `#278 → #280 / Issue #83` — 首轮稳定态取消保留；recovery completed；OpenCode Bundle `133`；4/4 tool；seq `1–48`；135.217s；in 110 / cached 8,582 / out 214 / reasoning 0；archives 7,552 / 15,078 B；MR !79；commit `571aabc5…` | frozen Provider `7 / openrouter-free`, `execute`, same failure→recovery semantics, fresh recovery session | pass（两条独立 lineage 均以 canonical delivery commit、唯一 marker 文件和清理闭合；#277/#278 failures 保留） |
| 20 | `#266 / Issue #75` — completed；9/9 tool；seq 1–188；184.220s；in 375 / cached 6,366 / out 2,391；archive 44,397 B；commit `7b1cc8f7…` | `#267/#269 / Issue #76` failures 保留；独立 `#270 / Issue #77` — completed；5/5 tool；seq 1–1233；234.985s；in 74 / cached 9,373 / out 2,906；archive 109,974 B；commit `0f43822c…` | frozen Provider `7 / openrouter-free`, high-token three-file prompt | pass（#270 `delivery.completed` + finalization 240/0；#267/#269 failures 保留） |

## Current stop boundary

- 2026-09-02 远端复核：`pending/queued/running=0`，`#320=completed`、`#321=cancelled`、
  `#322/#323=completed`、`#334=failed(engine_error)`、`#335=completed`；Profile 4 当前为
  generation `64`，最近一次 Verify 为 `2026-09-02 04:08:33.825663+00`。#334/#335 分别于
  `04:11:50` / `04:12:43+00` 启动，均落在 900s readiness TTL 内；下一次 canary 若超过该窗口必须
  重新 Verify。
- 最新 `docker --context remote system df` 显示 Images `66`（active `8`，size `8.187GB`，reclaimable
  `2.481GB`）、Containers `9` active（`38.45MB`，reclaimable `0B`）、Local Volumes `11`
  （active `4`，`1.632GB`，reclaimable `1.309GB`）和 Build Cache `552`（reclaimable `6.908GB`）；
  目标机未满，#334/#335 Worker container 已清理，不执行 broad prune，保留 active image ancestry、
  固定 Worker composition 和现有 cache。
- 远端磁盘当前未满；镜像、容器和 BuildKit cache 只在确有空间压力且逐项核对 container ancestry 后清理，
  不执行 broad prune。
- 当前没有运行中的任务时才切换全局 timeout；每次 timeout/cancel 样本结束后恢复 `1,800s`，并复核
  `pending/queued/running` 为空。
- 任一 Task 的实际 Profile、Image、Kit、Bundle、Provider protocol、attempt 或 Host platform 与本节
  不一致，立即停止该场景并保留失败证据。
- R3 只有 20 个场景全部有完整配对证据、统计和人工验收后才关闭；其后才进入 R4 UI/运维评审。
