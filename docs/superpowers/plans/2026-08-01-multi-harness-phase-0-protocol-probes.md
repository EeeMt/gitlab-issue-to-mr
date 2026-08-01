# Phase 0：Claude/Codex 协议探针与样本采集实施计划

> 上级计划：[Codify 多 Harness 引擎分阶段实施总计划](2026-08-01-multi-harness-engine-roadmap.md)

**目标：** 用固定版本的 Claude Code 和 Codex CLI 采集可审计的真实事件，冻结 Adapter 合同 v1、Canonical Event v1 和 golden fixtures，为后续重构消除命令、事件、session、usage 和进程终止语义上的猜测。

**周期：** 2–3 人日，计入双引擎生产候选总成本。

**行为边界：** 本阶段不切换生产 Worker，不修改现有任务执行路径；新增代码仅用于协议定义、探针、fixture 清洗与离线回放。

---

## 1. 前置条件

- [ ] 确定 Claude Code 与 Codex CLI 的精确版本、安装来源和校验摘要。
- [ ] 使用隔离测试仓库、隔离 Provider 账号和低权限短期凭据，禁止在真实业务仓库采集失败样本。
- [ ] 为限流、认证失败、网络中断准备可控测试条件，不通过泄漏或破坏生产凭据制造样本。
- [ ] 明确 raw fixture 的保留位置、访问权限和敏感信息清洗责任人。
- [ ] 记录 Worker 镜像、CPU 架构、容器权限、网络策略和 Docker Host；同一 fixture 必须能追溯运行环境。

---

## 2. 文件规划

### 协议与探针

- Create: `docs/architecture/worker-harness-contract-v1.md` — Adapter 能力、请求、事件、结果和错误合同。
- Create: `docs/architecture/worker-canonical-event-v1.md` — Canonical Event 字段、不变量、投影与兼容策略。
- Create: `scripts/harness-probes/README.md` — 安全前置、探针矩阵和证据记录方式。
- Create: `scripts/harness-probes/run-probe.sh` — 统一超时、信号、stdout/stderr、版本和退出码采集。
- Create: `scripts/harness-probes/sanitize_fixture.py` — 可重复的 token、路径、用户信息清洗和稳定化。

### 可执行协议与测试

- Create: `backend/app/core/harness_protocol.py` — `codify.worker.event/v1` envelope、terminal/usage/failure 校验。
- Create: `backend/tests/unit/test_harness_protocol.py` — schema、不变量和向前兼容测试。
- Create: `backend/tests/unit/test_harness_event_fixtures.py` — fixture manifest、敏感信息和成对回放校验。
- Create: `backend/tests/fixtures/harness_events/claude/` — Claude raw、metadata、expected canonical fixtures。
- Create: `backend/tests/fixtures/harness_events/codex/` — Codex raw、metadata、expected canonical fixtures。

fixture 每个场景使用独立目录：

```text
<harness>/<scenario>/
  metadata.json
  stdout.jsonl
  stderr.log
  process.json
  expected-canonical.jsonl
```

`metadata.json` 至少包含 CLI/Adapter 候选版本、镜像 digest、命令参数的脱敏表示、Provider 类型、协议、开始/结束时间和预期结果。不得保存 API Key、OAuth token、Cookie、真实用户目录或私有仓库 URL。

---

## 3. 任务拆分

### Task 0.1：冻结探针矩阵和 fixture 规范

**Files:**

- Create: `scripts/harness-probes/README.md`
- Create: `backend/tests/fixtures/harness_events/README.md`

- [ ] 列出两个 Harness 都必须覆盖的场景：普通成功、成功但无文件变化、工具成功、工具失败、新 session、正常 resume、无效 session、认证失败、限流、网络中断、timeout、SIGTERM、SIGKILL、取消、上下文压缩、usage/cost/模型解析。
- [ ] 为每个 Harness 场景指定 `harness.completed`/`harness.failed` 结果，并为合成的完整 attempt 指定最终 Task terminal 类别：`completed`、`failed`、`protocol_error` 或 `cancelled`；不能只按 Harness 退出码推断。
- [ ] 定义 fixture 命名、metadata 字段、原始输出保留和 expected canonical 对照规则。
- [ ] 定义敏感信息扫描模式，至少覆盖 GitLab token、Anthropic/OpenAI key、Bearer token、Cookie、私有 URL、用户目录和自定义 Provider token。
- [ ] 规定 raw 输出只允许在清洗后进入 Git；原始未清洗采集物写入临时受限目录并在验证后销毁。

**验证：** README 中的矩阵场景与设计方案 Phase 0 清单逐项对应，无“稍后补充”的必需 Harness 结束或 Task terminal 场景。

### Task 0.2：实现 Canonical Event v1 的可执行 schema

**Files:**

- Create: `backend/app/core/harness_protocol.py`
- Create: `backend/tests/unit/test_harness_protocol.py`
- Create: `docs/architecture/worker-canonical-event-v1.md`

- [ ] 先写失败测试，覆盖必填字段：`schema`、`event_id`、`attempt_id`、`seq`、`occurred_at`、`type`、`task_id`、`harness`、`payload` 和可选 `raw_ref`。
- [ ] 定义稳定事件类型：`run.started`、`model.resolved`、`message.*`、`reasoning_summary.*`、`tool.*`、`context.compacted`、`provider.retry`、`usage.*`、`harness.completed`、`harness.failed`、`delivery.*`、`worker.finalization`、`run.completed`、`run.failed`。
- [ ] 拒绝隐藏推理字段；只允许可展示的 reasoning summary。
- [ ] 定义 `(attempt_id, seq)` 单调递增、seq 从固定起点开始、event ID 唯一、单 Task terminal、terminal 必须是最后一个 canonical event 等不变量；`harness.*` 和 `delivery.*` 明确为非 terminal。
- [ ] 固定正常顺序：Harness translator 结束于 `harness.completed/failed`，公共交付层输出 `delivery.*`，清理/退出证据写入 `worker.finalization`，公共 runner 最后输出唯一 `run.completed/run.failed`。
- [ ] 定义未知 `type` 的兼容策略：未知非 terminal 事件降为 diagnostic 并保留 `raw_ref`；未知 Task terminal 不猜测成功。
- [ ] 定义 EOF 规则：缺 init、缺 Task terminal、seq 缺口、双 Task terminal、terminal 后仍有事件均产生 `protocol_error`；仅存在 `harness.completed` 不能推断 Task 成功。
- [ ] 定义 usage null 语义：不可得字段为 `null`，不得用 `0` 表示未知；Provider 特有字段保留在 `engine_fields`。

**验证：**

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_harness_protocol.py -v
```

### Task 0.3：实现可重复、安全的探针工具

**Files:**

- Create: `scripts/harness-probes/run-probe.sh`
- Create: `scripts/harness-probes/sanitize_fixture.py`
- Modify: `backend/tests/unit/test_harness_event_fixtures.py`

- [ ] `run-probe.sh` 记录命令版本、stdout、stderr、退出码、PID/PGID、收到的信号、开始/结束时间和超时后的 TERM/KILL 行为。
- [ ] 探针使用明确工作目录和临时 Harness home，不读取操作员全局配置。
- [ ] 探针禁止回显凭据；环境变量清单只记录 key 和来源，不记录 value。
- [ ] 清洗器使用固定占位符并保持 JSONL 结构、事件顺序和 session 关联可回放。
- [ ] 清洗器再次运行输出完全一致；对清洗后 fixture 运行敏感信息负面扫描。
- [ ] `bash -n`、Python 单测和一个完全离线的 fake CLI 自测通过后，才允许连接真实 Provider。

**验证：**

```bash
bash -n scripts/harness-probes/run-probe.sh
cd backend
.venv/bin/python -m pytest tests/unit/test_harness_event_fixtures.py -v
```

### Task 0.4：采集 Claude Code golden fixtures

**Files:**

- Create: `backend/tests/fixtures/harness_events/claude/*`
- Modify: `scripts/harness-probes/README.md`

- [ ] 用固定 Claude CLI 版本运行完整场景矩阵，记录实际命令、版本和环境摘要。
- [ ] 单独采集 `system/init`、stream delta、完整 assistant、tool use/result、compact boundary、result/usage/session 等事件形态；CLI result 只映射为 `harness.completed/failed`，不直接生成 Task terminal。
- [ ] 验证正常 resume 和无效 session 的实际行为；如 CLI 自动回退新 session，必须在 Adapter 合同中显式决定是否允许，不能照搬为默认。
- [ ] 验证收到 SIGTERM、最终 result 后 stream 不退出和强制 SIGKILL 时的输出与退出码。
- [ ] 清洗 fixtures，并人工复核 session、tool ID、序列和错误语义没有被清洗器破坏。
- [ ] 为每个 raw fixture 编写 expected canonical，不在公共协议中保留 Claude 专有字段名。

**完成证据：** CLI 版本、镜像 digest、场景结果表、清洗扫描结果和 fixture commit SHA。

### Task 0.5：采集 Codex golden fixtures

**Files:**

- Create: `backend/tests/fixtures/harness_events/codex/*`
- Modify: `scripts/harness-probes/README.md`

- [ ] 用固定 Codex CLI 版本验证 `exec --json` 的真实 JSONL 结构、新任务和 resume 命令差异。
- [ ] 采集 item/thread/turn 生命周期、工具调用、usage、模型解析、provider retry 和 CLI 结束事件；CLI 结束只映射为 `harness.completed/failed`。
- [ ] 分别验证容器内最小 sandbox、approval policy、sandbox 不可用、策略外操作和取消行为。
- [ ] 记录自定义 Responses Provider 的最小可用配置，不把 OpenAI Chat Completions 假设为等价协议。
- [ ] 记录 `CODEX_HOME` 隔离、用户全局配置是否被读取、仓库配置能否影响执行。
- [ ] 清洗并生成人工复核的 expected canonical；未知事件保留 diagnostic 证据。

**完成证据：** 与 Claude 相同，并额外包含 sandbox/approval 最终生效边界。

### Task 0.6：冻结 Adapter 合同 v1 和 capability 矩阵

**Files:**

- Create: `docs/architecture/worker-harness-contract-v1.md`
- Modify: `backend/app/core/harness_protocol.py`
- Modify: `backend/tests/unit/test_harness_protocol.py`

- [ ] 固定 `metadata`、`verify_runtime`、`detect_capabilities`、`prepare_config`、`build_command`、`materialize_skills`、`stream_events`、`normalize_result`、`terminate` 和可选 `run_text` 的输入输出。
- [ ] 定义 capability schema、未知 capability 忽略规则和公共逻辑的 allow/reject/degrade 行为。
- [ ] 记录 Claude/Codex 的版本范围与 feature detection 证据，版本只作为启动前快速拒绝，不替代启动事件探测。
- [ ] 定义 Adapter failure taxonomy：`configuration_error`、`authentication_error`、`rate_limited`、`sandbox_error`、`protocol_error`、`timeout`、`cancelled`、`engine_error`。
- [ ] 定义 session namespace 输入：Harness、Endpoint fingerprint、认证域、工作区身份和 Adapter state major version。
- [ ] 定义 Canonical Result v1，明确 usage/cost 的 null 语义和 capability warnings。

### Task 0.7：完成离线回放和阶段审查

**Files:**

- Modify: `backend/tests/unit/test_harness_event_fixtures.py`
- Modify: `docs/architecture/worker-harness-contract-v1.md`
- Modify: `docs/architecture/worker-canonical-event-v1.md`

- [ ] 每个 raw fixture 必须恰好对应一个 expected canonical 文件和 metadata。
- [ ] 对 success、Harness failure、delivery failure、cancel、timeout、invalid resume 和缺 Task terminal 做参数化回放。
- [ ] 对重复记录、乱序、seq 缺口、双 Task terminal、terminal 后追加、仅 Harness completed、未知事件和截断 JSONL 做负面测试。
- [ ] 审查公共协议中没有 `claude`/`codex` 原始事件字段；Harness 差异只存在 fixture 映射和 Adapter 合同附录。
- [ ] 审查文档与可执行 schema 一致；任何不确定点要转为 Phase 1 的阻断项，不能以隐式假设进入重构。

**阶段测试：**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_harness_protocol.py \
  tests/unit/test_harness_event_fixtures.py -v
```

---

## 4. Phase 0 退出门禁

- [ ] 两种 Harness 的所有必需场景都有已清洗 raw fixture、metadata 和 expected canonical。
- [ ] Adapter 合同和 Canonical Event v1 已通过代码与文档双重审查。
- [ ] session、usage、timeout、取消、Harness 结束和 Task terminal 语义来自真实探针与完整 attempt replay，不来自文档猜测。
- [ ] fixtures 中无凭据、私有仓库信息、真实用户目录或隐藏推理内容。
- [ ] 离线回放可在无网络、无 CLI、无 Provider 凭据的环境通过。
- [ ] 已明确 Phase 1 中 Claude 原始事件到 Canonical Event 的逐项映射。

任一必需 Harness 结束或 Task terminal 场景缺失时，不进入 Phase 1。
