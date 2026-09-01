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

## Pi command/recovery boundary

当前候选 Pi Task `179` 使用 Profile 4、Bundle `122`、Provider 7、Fresh session；attempt `task-179-attempt-1-aae2e80bb937` 的 `codify.worker.event/v2` seq 1–27 以唯一 `run.completed` 结束，control state 为 `closed`，archive `5,162` bytes，usage 为 input `55` / output `17` / total `72`。运行中 UI 曾显示 `Accepting commands`，说明当前 Bundle 的正常控制端点已启动；本 Task 没有额外 command row。

既有 live command/recovery 样本仍保留其原始 Bundle 边界：Bundle `111` 上的 Task `164` 为 `steer=delivered`，Task `165` 为 `outcome_unknown` / `delivery_outcome_unknown`，Task `166` 为 `control_gate_closed` 且记录 scheduler recovery 确认 Worker 容器不存在。它们不能直接替代 Bundle `122` 的同类 live rejection/recovery 证据，但与当前源码聚焦测试共同覆盖了命令幂等、严格顺序、closed gate、unknown outcome、CAS terminal 和 recovery。

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

- 已补齐：OpenCode `openai_chat_completions` 与 `openai_responses` 的当前 Bundle 成功链路、task-private namespace/config 隔离、Codex 当前 `openai_responses` 成功链路，以及当前 Pi Bundle 的正常运行和控制端点启动。
- 未关闭：Claude `anthropic_messages` 当前兼容 Provider 的成功链路；Pi 在当前 Bundle 上的 live rejection/unknown-outcome/Scheduler-recovery 组合；适用协议矩阵的完整当前-candidate success/failure 逐行收口。
- R3 正式 20-task benchmark、R4 L5 发布评审和 R5 L6 hard cut 均未开始；本文件中的 exploratory/debug Task 不计入 benchmark cohort。
