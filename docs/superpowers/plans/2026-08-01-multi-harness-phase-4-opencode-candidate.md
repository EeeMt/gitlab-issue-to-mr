# Phase 4：OpenCode 条件性候选接入实施计划

> 上级计划：[Codify 多 Harness 引擎分阶段实施总计划](2026-08-01-multi-harness-engine-roadmap.md)
> 强制前置：[Phase 3 Claude + Codex 多 Host 灰度与生产验收](2026-08-01-multi-harness-phase-3-production-rollout.md)

**目标：** 仅在双引擎协议已稳定且存在明确业务缺口时，为经过 allowlist 验证的 OpenCode Provider/能力子集增加第三 Harness 候选，并用它审计公共层是否真正与具体 Harness 解耦。

**周期：** 8–14 人日。

**优先级：** 最低、条件性。不得为了“三引擎数量对齐”启动；不得阻塞 Claude + Codex 的发布、修复和运维工作。

---

## 1. 强制准入审计

开始任何 Adapter 代码前，必须形成书面 Go/No-Go 记录并逐项满足：

- [ ] Claude + Codex 已完成真实 Host 灰度，并至少经过一个稳定 Worker Kit 发布周期。
- [ ] Backend Projector、Task API 和 Frontend 没有 Claude/Codex raw event 分支。
- [ ] Canonical Event v1 的 resume、cancel、rate limit、usage、Harness 结束与 Task terminal 边界、重复和缺序均有 fixture 与真实运行证据。
- [ ] 没有未解决的 P0/P1 双引擎运行缺陷。
- [ ] 有无法由 Claude/Codex 满足的明确业务需求、目标用户、Provider/模型和成功指标。
- [ ] 已证明项目级 OpenCode 配置、插件、自定义工具和 Provider 不能绕过 Codify 权限与 Provider allowlist。

任一项为否，结论必须是 **No-Go**，本阶段结束且不创建 OpenCode Adapter 空壳。

---

## 2. 文件规划

如果准入通过，优先只增加 Adapter、fixture 和 Runtime Bundle manifest；Worker Kit 只更新 compatibility manifest，公共 Backend/API/Frontend 理论上应通过 registry 自动发现，不应增加 `if harness == "opencode"`。

### Probe 与 fixtures

- Create: `backend/tests/fixtures/harness_events/opencode/`
- Extend: `scripts/harness-probes/run-probe.sh`
- Modify: `backend/tests/unit/test_harness_event_fixtures.py`
- Create: `backend/tests/unit/test_opencode_security_boundary.py`

### Adapter 与 Kit

- Create: `deploy/worker-entrypoint/harness/adapters/opencode.sh`
- Create: `deploy/worker-entrypoint/harness/adapters/opencode_events.py`
- Modify: `deploy/worker-entrypoint/harness/manifest.json` — Runtime Bundle 中实际 OpenCode Adapter version/digest 与 capability。
- Modify: `deploy/worker-entrypoint/harness/runner.sh` only if the v1 contract itself has a generic gap.
- Modify: `deploy/worker-entrypoint/verification.sh`
- Modify: `deploy/Dockerfile.worker-kit` — 只更新 bootstrap/compatibility manifest 和验证工具，不复制执行 Adapter。
- Modify: `deploy/worker-kit/verify-runtime.sh`
- Modify: `deploy/offline-bundle/scripts/verify-worker-runtime.sh`

### Registry、文档和测试

- Modify: `backend/app/core/harness_registry.py` — 注册内置 manifest，不新增 raw event 逻辑。
- Modify: `backend/app/core/model_endpoints.py` — 仅增加验证过的 Provider/driver 组合。
- Create: `backend/tests/unit/test_opencode_harness_adapter.py`
- Create: `backend/tests/mock_integration/fake_opencode/`
- Modify: `backend/tests/mock_integration/test_entrypoint.py`
- Modify: `docs/worker-kits.md`
- Create: `docs/runbooks/opencode-canary.md`
- Modify: frontend i18n only if registry display name/warning 不能由 API 表达。

如果实施需要修改 `worker_event_projector.py` 来理解 OpenCode raw 事件，或在 TaskForm 中增加 OpenCode 专用业务分支，应立即停止并回到公共协议设计审查。

---

## 3. 任务拆分

### Task 4.1：完成业务与安全 Go/No-Go

- [ ] 写清 Claude/Codex 无法满足的目标场景、目标 Provider/模型、预计任务量、运维责任人和退出条件。
- [ ] 固定待验证 OpenCode CLI 版本、安装来源、executable source/path、binary/image digest 和升级策略。
- [ ] 列出允许的 Provider/driver/model allowlist；不承诺 OpenCode 完整 Provider catalog。
- [ ] 确定 credential delivery 继续使用 Phase 2 的代理/Broker/短期 token 抽象，不新增长期容器密钥路径。
- [ ] 评估新增 Kit/CLI 的供应链、许可证、漏洞扫描、离线分发和回滚成本。
- [ ] 形成 Go/No-Go 审批；No-Go 时记录原因和下次重新评估条件。

### Task 4.2：证明 hermetic 配置与项目注入隔离

**Files:** security boundary test、probe docs/fixtures。

- [ ] 采集 OpenCode 全部配置来源及优先级，验证普通 `OPENCODE_CONFIG` 不能被误认为完全覆盖项目配置。
- [ ] 在恶意测试仓库放置项目 `opencode.json`、`.opencode`、插件、自定义工具、命令和 Provider 配置，证明它们不能突破 Codify managed config。
- [ ] 验证仓库不能修改 Provider base URL、credential source、插件 allowlist、网络、外部目录、shell deny 或系统工具策略。
- [ ] `--auto` 仅作为无人值守行为参数，不作为安全策略；生成显式 allow/ask/deny，并将 ask 在无人值守模式 fail closed。
- [ ] 如果目标版本无法通过容器级 managed config、禁用开关或受控 wrapper 建立隔离，立即 No-Go，不继续实现事件 Adapter。
- [ ] 保存负面测试 fixture 和脱敏日志，使后续 CLI 升级能重复验证。

### Task 4.3：采集 OpenCode 协议 fixtures 并评估 Canonical v1

**Files:** OpenCode fixtures、fixture tests、协议评估记录。

- [ ] 覆盖 Phase 0 同等级场景：成功/无变化、工具成功/失败、fresh/resume/invalid session、auth/rate limit/network、timeout/TERM/KILL/cancel、context、usage/model。
- [ ] 记录 `opencode run --format json` 的真实事件、session 和退出码，不从 Claude/Codex 结构类推。
- [ ] 生成 expected canonical 并验证 Canonical Event v1 能表达全部必需语义。
- [ ] 仅因为 Provider 特有扩展需要时放入 `engine_fields`；不要为原始字段增加公共 event type。
- [ ] 如果确有通用语义缺口，先提出向后兼容的 `v1.x` 扩展并让 Claude/Codex fixtures 全部回放通过；不得只为 OpenCode 破坏 v1。

### Task 4.4：实现 OpenCode Adapter

**Files:** OpenCode shell/translator、manifest、adapter tests。

- [ ] 实现 metadata、verify、capability detection、managed config、command、session、events、result、terminate 和可选 run_text。
- [ ] 命令只允许 Snapshot 中的 Provider/driver/model，不接受仓库动态注册的新 Provider。
- [ ] raw event 写入 `harness-events/opencode.jsonl`，canonical 写入通用 `event.jsonl`，应用现有清洗和权限策略。
- [ ] unknown raw event 产生 diagnostic；缺 init/Harness 结束语义按 protocol_error 失败。OpenCode result 只产生 `harness.completed/failed`；delivery/finalization 后的唯一 Task terminal 继续由公共 runner 产生。
- [ ] session namespace 包含 OpenCode state major version、Endpoint fingerprint 和认证域；不复用 Claude/Codex session。
- [ ] capability 精确声明 resume、Skills、usage、cost、run_text、sandbox/permission 和 CodeGraph，不追求表面全对齐。

### Task 4.5：适配 Provider、权限、Skills、usage 和取消

- [ ] `model_endpoints.py` 只加入通过真实 probe 的 Provider kind/driver/wire protocol 组合；wire protocol 不适用时使用 `null + provider_driver`。
- [ ] 明确限制外部目录、危险 shell、网络、插件、自定义工具和密钥访问；策略外行为 fail closed。
- [ ] 将中立 Skill 包物化到经版本测试确认的 `.agents/skills` 或 `.opencode/skills`，保持 runtime 目录只读且不污染 Git。
- [ ] usage/cost 无法稳定提供时返回 null 和 capability warning；不抓取非稳定 console 文本冒充精确统计。
- [ ] timeout/cancel 终止完整进程树，覆盖插件/工具产生的子进程。
- [ ] `run_text`、CodeGraph、max turns 等能力缺失走 Phase 2 已有公共 fallback，不增加 OpenCode 专用交付逻辑。

### Task 4.6：用第三 Harness 审计公共层纯度

- [ ] 搜索 Backend、Frontend、公共 Worker 中按 `claude|codex|opencode` 分支，区分合法 Adapter/registry/展示名与非法业务分支。
- [ ] Harness option、Task create/retry、不可变 Snapshot、session、usage、analytics 和 UI 通过 registry 数据自动工作；Task update 继续拒绝改写 Harness 等执行事实。
- [ ] 运行所有 Claude/Codex 回归，确认新增 manifest/capability 没有改变双引擎行为。
- [ ] 如果公共 contract 需要扩展，先用三套 fixtures 证明是通用需求，再修改协议与文档。

建议审计命令：

```bash
rg -n "claude|codex|opencode" \
  backend/app/core \
  backend/app/api \
  frontend/src \
  deploy/worker-entrypoint
```

审计结论应逐条分类，不能以搜索结果数量代替代码路径判断。

### Task 4.7：升级 Kit、真实 Host smoke 和独立 canary

- [ ] 发布新的不可变 Kit 版本；不覆盖双引擎稳定 Kit。Runtime Bundle manifest 记录实际 OpenCode Adapter version/digest，Kit manifest 只声明兼容范围。
- [ ] verify-runtime 增加 OpenCode executable source/path/version/binary digest、managed config、权限、Provider allowlist、Skills 和项目注入负面 smoke。
- [ ] 在独立 Profile 和 canary Host/队列运行完整验收矩阵，不修改双引擎默认 Profile；只把新创建的内部可信 Issue 分配到 OpenCode canary cohort。
- [ ] 只开放审批通过的 Provider/模型 allowlist；现有 Issue 不迁移 Profile，其后续 Task 继续走原双引擎 Profile。
- [ ] 观察成功率、P95、cancel、protocol error、权限拒绝、插件/配置注入和 credential warning。
- [ ] 演练回滚新 Issue 分配到双引擎稳定 Profile/Kit；既有 OpenCode canary Issue 如需继续，创建关联 replacement Issue，运行中的 OpenCode Task 按 Snapshot 完成或显式取消，不热切换 Harness。

---

## 4. 测试门禁

```bash
cd backend
.venv/bin/python -m pytest \
  tests/unit/test_opencode_security_boundary.py \
  tests/unit/test_opencode_harness_adapter.py \
  tests/unit/test_harness_event_fixtures.py \
  tests/unit/test_harness_registry.py \
  tests/unit/test_model_endpoints.py \
  tests/mock_integration/test_entrypoint.py -v
```

```bash
make test-backend
make test-frontend
make test-mock-e2e
```

同时重新运行 Claude/Codex golden fixtures、single Host smoke 和 Kit verification；第三 Harness 的新增测试不能替代原双引擎回归。

---

## 5. Phase 4 完成或退出条件

OpenCode 只有在以下条件全部满足时才可称为候选：

- [ ] 项目配置、插件、自定义工具和 Provider 注入不能绕过 managed policy。
- [ ] 仅 allowlist Provider/模型可用，credential 继续走安全抽象。
- [ ] Adapter 完整覆盖事件、session、usage、取消、Skills 和失败语义。
- [ ] 公共 Backend/Frontend/Worker 无 OpenCode raw 分支，Claude/Codex 无回归。
- [ ] 新 Kit、真实 Host smoke、新 Issue canary cohort 指标和恢复双引擎新 Issue 分配的回滚演练完整。

若 hermetic 配置、安全边界、Provider allowlist 或无人值守权限任一项无法证明，正确结果是停止接入并保留 Claude + Codex 生产基线，而不是降低系统上限。
