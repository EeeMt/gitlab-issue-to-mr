# Open-Harness V2 R2 Candidate Evidence

本文件记录 2026-09-01 在目标开发 Host 上的 R2 现场复核。它是可追溯证据，不代表 R2–R5 或 L6 已全部通过。

## Scope and fixed identity

- Host：`192.168.50.129`
- 平台：`linux/amd64`
- 执行模式：`dual_canary`
- Profile：`4 / v2-canary-0.6.11-four-harness`
- Worker Kit：`0.6.11`
- Worker image：`127.0.0.1:5000/codify-worker/java21-maven@sha256:234582c692d1ebb00ba8e882160618c2258463149d968009ac81c545e63a538b`
- 本轮 remote Docker 磁盘未满，因此没有执行镜像清理或 broad prune。

## OpenCode endpoint/config isolation

两个真实 Task 都通过 UI 创建为 Profile 4、OpenCode、Fresh session，并在同一 Issue 的连续工作分支上只新增各自的一个标记文件。

| Task | Provider / protocol | Bundle / attempt | namespace / HTTP audit | canonical / usage | archive / delivery |
| --- | --- | --- | --- | --- | --- |
| `177` | `openrouter-free` / `openai_chat_completions` | Bundle `119`, Adapter `2.0.0`, CLI `1.18.19`, `task-177-attempt-1-fc96f35b0c7b` | `opencode-e2b9ebf6c92f09f9`; endpoint `v2:851c2f91275f1420238eb5455715d35e`; config SHA `6591a62d9a8e92fbc57c9a0a5fb51611f1d6eedba00b9ce18f945804c9100de5` | `event.jsonl` seq 1–100 连续，唯一终态 `run.completed`；input `156` / output `114` / total `270` | archive `18,547` bytes；commit `df795ac45263df299d93f85db2baa56900dca7e0`；只新增 `r2-opencode-namespace-chat-20260901.txt` |
| `178` | `openrouter-minimax-responses` / `openai_responses` | Bundle `119`, Adapter `2.0.0`, CLI `1.18.19`, `task-178-attempt-1-275d2015189e` | `opencode-0d369f3d768c792c`; endpoint `v2:5747348962c979643f612fa1755ddb12`; config SHA `f847378c5e8181b368749f914a3d2e2206461f83376167fb12b26b5756279dac` | `event.jsonl` seq 1–60 连续，唯一终态 `run.completed`；input `736` / output `46` / total `782` | archive `15,846` bytes；commit `b75b13aef1c125cd04abe741746d982b238150f8`；只新增 `r2-opencode-namespace-responses-20260901.txt` |

两条 audit 都记录 `POST /session=200`、`POST /session/{session_id}/prompt_async=204` 和 `GET /event=200` 后关闭，配置路径均为 task-local 的 `/tmp/codify-runtime/opencode/opencode.json`。namespace、endpoint fingerprint、config SHA 和 session ID 均不同；GitLab 两个 commit 各自只有一个新增文件，证明没有把另一条 endpoint/config 的运行上下文未声明串入当前 Task。Issue 工作区复用导致后一条任务能看到前一条已交付文件，这是预期的 repository/worktree 行为，不是 session namespace 泄漏。

## Codex and Claude current candidates

- Codex Task `173` 使用 Profile 4、Bundle `120`、`openrouter-minimax-responses` 的 `openai_responses`，真实执行成功并完成 canonical/archive/usage/GitLab delivery：input `66,400`、output `542`，archive `6,610` bytes，commit `9cfe6f0796bdfc8fb836e4517b749fe6afbea261`。同 Provider 的 Codex Task `172` 因 OpenCode Zen 真实 `429` 失败，原样保留，不能作为成功。
- Claude Task `174` 使用 `openrouter-minimax-anthropic` / `minimax/minimax-m3:free`，Task `175` 使用 `openrouter-glm52-anthropic` / `z-ai/glm-5.2:free`；两条真实 `anthropic_messages` 请求均返回 `404 model_not_found`，token 为零且没有代码提交。它们证明了当前 Provider access/capacity 的真实失败分类，但没有关闭 Claude 成功 conformance。已知受限的 OpenCode Zen Provider 没有重复消耗，也没有用不兼容协议冒充 Claude 成功。
- 当前 Profile 4 的 Claude Task `186` 又在 Claude Bundle `121` 上复核了同一失败边界：Provider 11（`openrouter-minimax-anthropic` / `minimax/minimax-m3:free`）、Fresh session、attempt `task-186-attempt-1-64a1bde06c84`，`codify.worker.event/v2` seq `1–7` 以唯一 `run.failed` 结束，Adapter `1.0.1`、CLI `2.1.153`，runtime archive `4,144` bytes，usage input/output 均为 `0`，无 commit；CLI 返回 `404 / model_not_found`（model may not exist or may not be accessible）。该样本把失败分类推进到当前 Claude candidate，但仍不能替代兼容 Provider 的成功 conformance。
- 修正 Provider-11 的 endpoint 前，配置页编辑会因为同时提交 `openai_compatible + anthropic_messages` 却遗漏已有的 `provider_driver=openrouter` 而返回 `422`；提交 `4642ad60` 让编辑表单保留该 driver。随后通过 UI 将 Provider-11 的根地址保存为 `https://openrouter.ai/api`，保留 model `minimax/minimax-m3:free`、protocol `anthropic_messages` 和 `provider_driver=openrouter`。
- 当前 Profile 4 的 Claude Task `187` 在该修正配置上完成了真实成功链路：Provider 11、Fresh session、Bundle `121`、attempt `task-187-attempt-1-e42c7e95c99a`，projected namespace `claude-26dcac44aab5d23b`，session `8a1e8896-0536-48ee-b3c6-569b0781f3b6`。任务表快照记录 `base_url=https://openrouter.ai/api`、`model_protocol=anthropic_messages`；canonical receipts seq `1–15` 连续，唯一终态为 `run.completed`，control state closed；runtime archive `6,421` bytes，SHA-256 `b9924bcbfaead8001c7f1ef8ba40504f55d8a230a8fd1c9b8711392cbbc6e934`，`codify.worker.result/v2`、Adapter `1.0.1`、CLI `2.1.153`，usage input `4,284` / output `244` / total `4,528`，delivery validation `ok=true`，commit `4c2b2a0472352bcf5d587645de2e9697d802878b`，仅新增 `r2-claude-anthropic-root-20260901.txt`。任务页显示 `Completed`、`Fresh session`、Claude 和 Provider-11，Worker 容器随后已清理。
- Task `188` 在同一 Provider 11、Profile 4、Bundle `121` 上继续 Task `187` 的 Claude session：attempt `task-188-attempt-1-d1159279343d`，输入/输出 session 均为 `8a1e8896-0536-48ee-b3c6-569b0781f3b6`，projected namespace 为 `claude-26dcac44aab5d23b`；canonical receipts seq `1–14` 连续，唯一终态为 `run.completed`，事件链包含 `message.completed`、`usage.final`、`harness.completed`、`delivery.completed` 和 `worker.finalization`。任务记录 input `5,254` / output `210`，runtime archive `6,337` bytes、SHA-256 `c3f4f491618f0f85a977de0665fe1009726a6a94510a889590b150f593aa19fb`，commit `a0c3cfac9d2dee402563e8b3fc922cadfe6b8b5e`，仅新增 `r2-claude-anthropic-continue-20260901.txt`，Worker 容器已清理。
- Task `189` 保留为 early-cancel race 证据：UI 在 Worker 发布稳定 container ID 前取消，API 返回“cancellation remains pending”，随后后台在创建 Worker 前收敛为 `cancelled`；无 attempt、archive、usage 或 commit。因此它不是 Harness cancellation conformance，不能替代稳定态取消样本。
- Task `190` 在同一 Provider 11、Profile 4、Bundle `121` 上完成了稳定态 Claude 取消：先确认 Worker/container ID 和 attempt `task-190-attempt-1-f1a4ca53f92d` 已初始化，并已持久化首个 `sleep 180` 的 `tool.started`，再通过 UI 取消。canonical receipts seq `1–7` 连续，唯一终态为 `run.failed`，事件链为 `run.started, model.resolved, diagnostic, tool.started, harness.failed, worker.finalization, run.failed`；TaskLog 的 `harness.failed` 为 `kind=cancelled`、Worker exit `143`，无 token、diff 或 commit，runtime archive `4,068` bytes、SHA-256 `104a15902b508c9d365b553741244b6a38ea50341b5a419989db96b1713592da`，Worker 容器已清理。
- Task `191` 完成了同一 Claude candidate 的自动 timeout：Runtime 的全局 Task Timeout 临时从 `1,800` 秒调整为最小可保存值 `60` 秒，任务结束后已恢复为 `1,800` 秒；Task 使用 Provider 11、Profile 4、Bundle `121`、Fresh session，attempt `task-191-attempt-1-4f35e56499be` 的 canonical receipts seq `1–7` 连续，唯一终态为 `run.failed`，事件链为 `run.started, model.resolved, diagnostic, tool.started, harness.failed, worker.finalization, run.failed`。Task 记录 `Task timed out after 60s`，TaskLog 明确 `sleep 180`、`failure.kind=timeout`、Worker exit `143`、零 diff、无 token 和 commit；runtime archive `4,445` bytes、SHA-256 `a1030ff5b2a8637526261eece79271d37920867081f8a205bcab14106f864821`，Worker 容器已清理。
- Task `186`、`187`、`188`、`190` 和 `191` 共同证明了当前 Claude candidate 的真实 failure/success、endpoint 根路径修正、continue、稳定态取消和 timeout 分类；Task `189` 的创建前取消 race 单独保留。适用协议矩阵的完整当前-candidate success/failure 与生命周期逐行收口仍未完成。

## Pi command/recovery boundary

当前候选 Pi Task `179` 使用 Profile 4、Bundle `122`、Provider 7、Fresh session；attempt `task-179-attempt-1-aae2e80bb937` 的 `codify.worker.event/v2` seq 1–27 以唯一 `run.completed` 结束，control state 为 `closed`，archive `5,162` bytes，usage 为 input `55` / output `17` / total `72`。运行中 UI 曾显示 `Accepting commands`，说明当前 Bundle 的正常控制端点已启动；本 Task 没有额外 command row。

本轮又在当前 Bundle `122` 上执行了 Task `181` 的受控恢复竞态：Task 使用 Profile 4、Provider 7、Pi、Fresh session，attempt 为 `task-181-attempt-1-2c78af685c5f`，Bundle digest 为 `9d14951d9abf94c70754364cd54efcc534d49d82e567ad4710cc1c1cce5a465a`，projected namespace 为 `pi-bb870ebba4d70be9`。attempt 进入 `accepting` 后，先暂停 `codify-scheduler`，再通过已登录任务页写入 command `a071d0ad-ed0d-4368-b375-3821143f4623`（seq `1`，`queued`）；随后只移除了已核对的 Worker `codify-181-issue18` / container `8f7c94f4bc32cece7462c76358c99bb609ed8a4efa439179fef41cbc58afbcc4`，启动 scheduler。恢复日志确认 Docker daemon 可达但容器不存在，Task `181` 被标记为 `failed`，error 为 `Task was running when scheduler restarted (container not found)`；attempt 最终为 `closed`、last seq `12`，command 变为 `rejected` / `control_gate_closed`，rejection message 为 `scheduler recovery confirmed worker container absent`，`delivery_attempts=0` 且没有 `native_request_id`。任务页同步显示 `Failed`、Live steering `Closed` 和 command `Rejected`。

Task `181` 是当前 Bundle 的 live rejection/recovery 证据，不是成功样本：因故意移除 Worker，没有形成完整 terminal event、runtime archive 或 usage ledger。

随后在同一 Bundle `122` 上执行了 Task `182` 的正常 command/cancel 样本：attempt `task-182-attempt-1-dd408a81260c` 进入 `accepting` 后，command `b41fcdb2-04e0-448e-a1d6-e0169b560255`（seq `1`）由当前 Pi pump 实际送达，`delivery_attempts=1`、native request `1000001`，任务页最终显示 `Delivered`。随后通过 UI 取消 Task，attempt 以唯一 `run.failed` 终止、control state 为 `closed`、canonical seq `1–21` 连续，runtime archive 为 `4,606` bytes，Worker 容器已清理。该样本证明当前 Bundle 的真实 command delivery 与取消收敛；后续 Task `184` 另行补齐了 dispatcher crash/recovery 后的 `dispatching → outcome_unknown` 证据。

随后在同一 Bundle `122` 上执行了 Task `184` 的 dispatcher crash-recovery 样本：attempt `task-184-attempt-1-46fde9a7844f` 进入 `accepting` 后，command `b9f120f4-b22f-4978-88b5-7022ce8543a5`（seq `1`）持久化为 `dispatching`、`delivery_attempts=1`、没有 `native_request_id`；随后仅强制终止 scheduler，保留 Worker 容器并重新启动 scheduler。重启后的 recovery 在旧 dispatcher lease 到期后将该命令不可重放地收敛为 `outcome_unknown` / `delivery_outcome_unknown`，rejection message 为 `dispatcher recovery cannot prove native send outcome`。取消 Task 后，attempt 以唯一 `run.failed` 终止、control state 为 `closed`、canonical seq `1–17` 连续，runtime archive 为 `4,201` bytes；任务页显示 `Closed` 和 `Outcome unknown`，Worker 容器已清理。
随后在当前 Bundle `122` 上执行了 Task `185` 的 Pi `openai_responses` 真实成功样本：Task 使用 Profile 4、Provider 12（`openrouter-minimax-responses` / `minimax/minimax-m3:free`）、Fresh session，attempt `task-185-attempt-1-50a99aa604a6`，harness `pi`、Adapter `2.0.0`、CLI `0.84.2`，projected namespace `pi-47a852ca5d9ce075`。canonical receipts seq `1–75` 以唯一 `run.completed` 结束，control state 为 `closed`；usage 为 input `143` / output `120` / total `263`，runtime archive `9,594` bytes，commit `d2c4ec29ac637a9f3494022818a2e23b592c6355`，delivery summary validation 通过，任务页显示 `Completed`、`Fresh session` 和对应 Provider/Harness。该样本关闭当前 Bundle Pi 的 `openai_responses` success 行；容器退出后的 canonical tail warning 不影响已持久化 receipts/archive，不应表述为 error-free tail。

既有 live command/recovery 样本仍保留其原始 Bundle 边界：Bundle `111` 上的 Task `164` 为 `steer=delivered`，Task `165` 为 `outcome_unknown` / `delivery_outcome_unknown`，Task `166` 为 `control_gate_closed` 且记录 scheduler recovery 确认 Worker 容器不存在。旧样本不能替代当前 Bundle 的成功运行身份，但与当前 Bundle 的 Task `181`、`182`、`184` 及当前源码聚焦测试共同覆盖了 delivered、closed-gate rejection、unknown outcome、CAS terminal 和两类 recovery。

本轮执行的聚焦套件为：

```text
backend/.venv/bin/python -m pytest -q \
  backend/tests/unit/test_task_command_routes.py \
  backend/tests/unit/test_task_harness_commands.py \
  backend/tests/unit/test_worker_command_pump.py \
  backend/tests/unit/test_harness_attempts.py \
  backend/tests/unit/test_scheduler_harness_gate.py \
  backend/tests/unit/test_worker_results_v2.py \
  backend/tests/unit/test_task_event_archive.py \
  backend/tests/unit/test_worker_archive_streaming.py
```

结果：`93 passed, 10 subtests passed in 62.79s`。

## Current R2 boundary

- 已补齐：OpenCode `openai_chat_completions` 与 `openai_responses` 的当前 Bundle 成功链路、task-private namespace/config 隔离、Codex 当前 `openai_responses` 成功链路，以及当前 Pi Bundle 的正常运行、`openai_responses` 成功、控制端点启动、command delivery/cancel、Worker 缺失后的 live rejection/recovery 和 dispatcher crash-recovery unknown outcome；Claude 当前 candidate 的 `anthropic_messages` fresh success、continue、稳定态取消和 timeout 也已补证。
- 未关闭：适用协议矩阵的完整当前-candidate success/failure 与生命周期逐行收口；Task `189` 的 early-cancel race 不能替代 Harness cancellation conformance。Task `186` 的 `404 / model_not_found` 失败、Task `187` 的 endpoint 修正后成功及 Tasks `188`、`190`、`191` 均已归档。
- R3 正式 20-task benchmark、R4 L5 发布评审和 R5 L6 hard cut 均未开始；本文件中的 exploratory/debug Task 不计入 benchmark cohort。
