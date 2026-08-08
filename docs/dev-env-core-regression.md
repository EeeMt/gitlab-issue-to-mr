# Codify 核心功能开发环境回归计划

> 面向 worker/task 大规模改造（Multi-Harness 引擎）之后的核心功能开发环境回归。
> 这是一份**可复用的分层回归计划**：不仅用于本次本地回归，也作为以后每次 worker/task 改动、
> 里程碑、发版前的固定验证基线。

## 0. 文档定位

| 文档 | 定位 |
|---|---|
| 本文档 | 面向**核心功能**的分层回归计划（冒烟 / 完整 / 发版演练），覆盖 issue→task→worker→delivery→MR→analytics→config 全链路 |
| [`dev-env-api-regression.md`](./dev-env-api-regression.md) | 偏 **Phase 1 L4 API 级**验证手册，含具体 curl 步骤与已知问题细节，本文档的「操作要点」引用它 |
| [`multi-harness-debugging.md`](./multi-harness-debugging.md) | Multi-Harness 接入调试与通用经验：通用接入断层清单（含 codex 专项）与验证命令速查 |

**职责划分：** 单测 / mock-e2e / mock-integration / Playwright 覆盖代码逻辑与模拟环境的自动化回归
（详见 [TESTING.md](./TESTING.md)）；本文档覆盖**只有真实环境才能验证**的 L4 层——真实 GitLab、
真实 Harness CLI、真实远程 Docker Host、真实 Provider/凭据。

### 使用时机（触发清单）

| 触发改动 | 最低执行 |
|---|---|
| `deploy/worker-entrypoint/**`、`deploy/ci-claude.sh`、`harness/**`（adapter/translator/sanitizer） | Tier 1（双 harness）+ §5 回归点核查 |
| backend worker / scheduler / session / protocol / bundle 代码 | Tier 1 + 相关 §3 完整项 |
| 新增 Alembic 迁移 | Tier 2 + §6 数据一致性 |
| provider / credential / worker-profile 代码 | Tier 2 §J + §5 |
| 前端 task/harness/worker-profile UI | Tier 1 + §3 K UI 冒烟 |
| 里程碑 / 发版前 | Tier 2 + Tier 3（Phase 3 演练） |

> **改动 worker 脚本后的关键前提**：worker 容器执行的 entrypoint 来自 Task Runtime Bundle
> （backend 在任务创建时从镜像内 `/opt/codify/runtime-source` 生成）。改了
> `deploy/worker-entrypoint/**` 或 `ci-claude.sh` 后必须 **重建 backend 镜像并 recreate scheduler**
> （`make rebuild-backend` + `docker-compose --env-file .env.test up -d scheduler`），否则验证的是旧脚本；
> retry 任务复用旧 bundle digest，**要验证新改动必须新建任务**。详见
> [`dev-env-api-regression.md` §8](./dev-env-api-regression.md)。

---

## 1. 环境与前提

### 1.1 拓扑

- 开发环境由 `make up` 启动（backend / scheduler / nginx / postgres，代码烘焙进镜像，postgres 持久化在 named volume）。
- Docker 通过 **remote context** 连到目标主机（`docker context show` 应为 `remote` → `ssh://root@<host>`）；
  构建与容器都发生在目标主机上。页面入口 `http://<host>:8880`，`/api/*` 由 nginx 反代到 backend。
- API 全部要求 session cookie；管理员接口（GitLab 连通性测试、provider 增改、profile 编辑）需要 `platform_admin` 角色。

### 1.2 基线检查（未认证）

```bash
curl -s http://<host>:8880/api/auth/bootstrap-status
# {"initialized":true,"oidc_configured":true,"total_users":N}
```

### 1.3 前置准备与 preflight

一次性准备：

- [ ] 一个**可写分支的测试项目**（dev GitLab 上 bot 有推送权限）。脚本每次运行会自动在其上新建 issue；
      或用 `ISSUE_ID=<现有issue>` 复用已有 issue（须 lineage 干净，用于 resume 场景）。

Preflight 检查（Tier 1 由 [`scripts/dev-regression.sh`](../../scripts/dev-regression.sh) 自动执行；完整回归前手动核对）：

```bash
# 1. 环境就绪（无需认证）
curl -s http://<host>:8880/api/auth/bootstrap-status

# 2. GitLab 连通（需登录 cookie + platform_admin）
curl -s -b /tmp/codify_cookies.txt -X POST http://<host>:8880/api/config/gitlab/test \
  -H 'Content-Type: application/json' -d '{"integration":{}}'
# 期望：{"server_version":..., "username":..., "gitlab_url":...}

# 3. Provider 就绪：claude(anthropic_messages) 与 codex(openai_responses) 各至少一个
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/providers \
  | python3 -c "import sys,json; print([(p['id'],p['wire_protocol'],p['credential_status']) for p in json.load(sys.stdin)])"

# 4. Worker Profile 就绪：enabled_harnesses 含 claude+codex，verify-runtime 通过
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/worker-profiles
```

**Tier 1 半自动脚本**（登录 / preflight / 自动建 issue / 双 harness happy path / resume / archive 校验全自动）：

```bash
./scripts/dev-regression.sh                        # 自动选第一个可访问项目 + 新建 issue
./scripts/dev-regression.sh --tier2                # 追加故障路径（切换约束/cancel/timeout/retry）
PROJECT_ID=<测试项目> ./scripts/dev-regression.sh  # 在指定项目上新建 issue
ISSUE_ID=<现有issue> ./scripts/dev-regression.sh   # 复用已有 issue
```

> 凭据与地址优先从 `deploy/dev-env-info.md`（gitignored）读取，也可用 `CODIFY_BASE_URL`/`CODIFY_USER`/`CODIFY_PASS`/`PROJECT_ID`/`PROVIDER_CLAUDE_ID`/`PROVIDER_CODEX_ID` 环境变量覆盖；脚本不含明文凭据。

---

## 2. 分层执行模型

| 层级 | 覆盖 | 预计耗时 | 用途 |
|---|---|---|---|
| **Tier 1 冒烟** | 双 harness 各一条 happy path + MR + archive + sanitize + resume 一条 | ~15–25 min | 每次 worker/task 改动后 |

> Tier 1 可用 [`scripts/dev-regression.sh`](../../scripts/dev-regression.sh) 半自动执行（§1.3）；加 `--tier2`
> 会追加故障路径（切换约束 / cancel / timeout / retry 冻结），见脚本头注释。Tier 2 其余项（调度、analytics、config）仍建议人主导 + agent 辅助。
| **Tier 2 完整回归** | §3 全矩阵 + §4 双引擎 × 故障路径 + §6 一致性 | ~1–1.5 h | 里程碑 / 发版前 |
| **Tier 3 发版演练** | Phase 3 rollout drill（冻结清单核对、验证、切换、回滚演练） | 半天 | 发版收口 |

Tier 1 通过是 Tier 2 的前置；Tier 2 通过是发版的前置。执行顺序固定，避免跳层。

---

## 3. 核心功能回归矩阵

> 操作要点里的 curl 详见 [`dev-env-api-regression.md`](./dev-env-api-regression.md)；
> 「强度」列：S = Tier 1 冒烟必做，F = Tier 2 完整回归才做。

### A. 环境基线

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| A1 | 服务健康 | `GET /api/health*`、`docker compose ps` | 四服务 running，无 restart 循环 | S |
| A2 | bootstrap / 认证 | `bootstrap-status` + 本地登录 | 登录成功，cookie 有效，`/api/tasks` 不再 401 | S |

### B. Issue 生命周期

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| B1 | Issue 创建 | `POST /api/issues`（带默认 harness 字段） | 201；`default_harness_key` 落库；列表/详情可见 | F |
| B2 | Issue 关闭 + 分支清理 | close 后 `delete-branch` | 分支删除成功；issue `closed` | F |

### C. Task 生命周期

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| C1 | 创建（execute / fresh） | `POST /api/tasks`（claude，`require_changes:true`） | 事务内冻结 `TaskWorkerProfileSnapshot` + 绑定不可变 Runtime Bundle；`pending → queued → running` | S |
| C2 | 创建（plan 模式） | `task_mode:"plan"` | 只出方案不写文件；`commit_sha=null` 但 `status=completed` | F |
| C3 | 轮询终态 | `GET /api/tasks/{id}` | `status=completed`、`commit_sha` 非空（execute）、`error_message=null` | S |
| C4 | 取消（RUNNING） | `POST /api/tasks/{id}/cancel` | `status=cancelled`；canonical `harness.failed(cancelled)→run.failed(cancelled)`；容器清理；archive 保留 | S |
| C5 | 取消（run.started 前，极早） | 创建后立即取消 | archive 保留（console.log + repository-preparation）；无 canonical 终态属设计行为 | F |
| C6 | 超时 | 临时 `PATCH /api/config/runtime` 设 `task_timeout=60` → 建较重任务 → **恢复原值**（默认 1800，部分环境 3700） | `status=failed`，error `Task timed out after Ns`；canonical `harness.failed(timeout)`；**测完必须恢复** | F |
| C7 | 重试 | `POST /api/tasks/{id}/retry`（对失败任务） | 复制源任务 Harness/Adapter/Endpoint/Bundle；bundle digest 与源一致；completed | F |
| C8 | 状态覆盖 | `POST /api/tasks/{id}/override-status`（管理员） | 状态可被强制覆盖且日志可追溯 | F |

### D. 调度

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| D1 | 优先级 | 同时排队 P0/P1/P2 任务 | P0 先执行；队列按优先级出队 | F |
| D2 | 并发上限 | `MAX_CONCURRENCY`（默认 3）内同时多任务 | 运行数不超过上限；日志 `Max concurrency reached` | F |
| D3 | Issue 互斥 | 同 issue 再触发任务 | 被 `_running_issues` 挡下，不并发执行 | F |
| D4 | 崩溃恢复 | 杀 scheduler 后重启 | 孤儿容器按 `codify-{task_id}-p{pid}-i{iid}` 模式清理；`_running_*` 与 DB 重对齐 | F |

### E. Worker 执行 · Harness

> 双引擎行为差异与回归点见 §4。

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| E1 | claude 全流程 | 真实 claude 任务 | `run.completed(success)`；commit+MR；`session_id` 真实 UUID | S |
| E2 | codex 全流程 | 真实 codex 任务（`harness_key:"codex"`） | `run.completed(success)`；commit+MR；`session_id` 真实 UUID | S |
| E3 | 运行用户 | 任务 prompt 执行 `id -u` 写文件；`docker exec` 现场看进程 | 文件/`.git` 均为 codify（uid 1000）所有；无 root-owned 遗留 | F |
| E4 | 沙箱模式 | archive 里 `run.started` 的 `sandbox` 字段 | `sandbox=container-boundary`（生产默认）；codex execpolicy 禁止 git 写操作 | F |

### F. Delivery · MR

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| F1 | commit + push | execute 任务 | `delivery.completed` 携带 `commit_sha`；work 分支领先 base | S |
| F2 | MR 引用 | `GET /api/tasks/{id}` 的 `issue.merge_request_url` | MR 存在；worker 更新已有 MR 描述或新建 MR | S |
| F3 | 无变更语义 | `require_changes:true` 且 harness 无产出 | `status=failed`（不误判成功） | F |
| F4 | codex 已发布 commit 复用 | codex 自 commit 场景 | `repo_work_branch_ahead_of_base`（基线 `REPO_REMOTE_WORK_SHA`）正确识别本次任务新 commit，不复用历史 commit | F |

### G. Canonical 协议 · Archive · 脱敏

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| G1 | event.jsonl 不变量 | 下载 archive 校验（§6 脚本） | seq 连续无缺口无重复；schema v1；**只有一个** run terminal；terminal 最后出现；含 `worker.finalization` | S |
| G2 | harness-result | `harness-result.json` | `harness_key`/`adapter_version`/`cli_version`/`session_id` 齐全；`session_id` 为真实 UUID | S |
| G3 | 脱敏 | 扫描 `error_message`、event.jsonl | 无 `glpat-*`、`sk-ant-*` 残留；codex cookie/path/tool-id 已掩码 | S |
| G4 | archive 下载 | `GET /api/tasks/{id}/archive/download` | 下载成功，可 `tar tzvf` 列出事件/harness 流 | S |
| G5 | 失败分类 | 触发 auth/rate-limit（用失效凭据/限流端点） | canonical 正确分类：`error→provider.retry`、`turn.failed→harness.failed`（401/429/sandbox） | F |

### H. 会话 / Resume 链路

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| H1 | fresh → continue | 先 fresh 任务记录真实 session，再 `session_mode:"continue"` | continue 用 `--resume <真实UUID>`；`input_session` 非空；completed | S |
| H2 | harness 切换约束 | continue 显式传与 lineage 不同的 `harness_key` | 422「续跑会话必须沿用原 Harness；切换请勾选使用新会话执行」 | F |
| H3 | 跨 harness 隔离 | claude fresh 出 session A，codex continue | `input_session_id` 为空（不复用 claude session）；lineage 不串 | F |
| H4 | resume 失败语义 | continue 一个已完成的会话 | 不猜测成功；按 turn-terminal 语义正确判终态 | F |

### I. Analytics / Stats

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| I1 | per-harness 统计 | `GET /api/stats/analytics` | `succeeded_tasks` 按 claude/codex 分别正确计数（boolean finished 谓词） | F |
| I2 | usage | `GET /api/tasks/{id}` usage 字段 | 双 harness 均产出 token/usage，null-safe | F |
| I3 | 汇总/热力图 | `GET /api/stats`、`/stats/activity-heatmap` | 数字与任务实况一致 | F |

### J. Config · Provider · Credential · Worker Profile

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| J1 | harness options 一致 | 前端 TaskFormDrawer / Issue 创建页 | 选择器选项来自 backend `harness_options`/`compatible_harnesses`，前端**不复制**兼容规则 | S |
| J2 | provider 增改 | `POST/PATCH /api/providers`（kind↔protocol 配对校验） | 创建绑独立 `ModelCredential`（`credential_ref`）；更新轮换旧凭据 | F |
| J3 | provider 删除 | `DELETE /api/providers/{id}` | 凭据只 soft-retire 不硬删；既有 retry 仍可解析 | F |
| J4 | verify-runtime | `POST /api/worker-profiles/{id}/verify-runtime` | Kit/Adapter/CLI/CA/sandbox/工作区写权限全过；profile 变更置 stale | F |
| J5 | 能力一致性 | profile snapshot 的 harness capabilities | claude `run_text=true`；codex `run_text=false`/`max_turns=false`/`codegraph=false`（manifest ↔ registry ↔ UI 三方一致） | S |
| J6 | 发版硬边界 | 对迁移前无 bundle 的历史任务 retry/execute | 拒绝；历史任务只读/关闭 | F |
| J7 | WorkerSettingsPanel 保存 | 编辑 `enabled_harnesses`/`default_harness_key`/`harness_constraints` 保存再读 | 三字段**不静默还原**（修复 P1#2 的回归点） | S |

### K. UI 冒烟

| # | 场景 | 操作要点 | 预期结果 | 强度 |
|---|---|---|---|---|
| K1 | Dashboard 任务列表 | 展示 harness 引擎标识；P0/P1/P2 分 tab | 双 harness 任务均正确显示 | S |
| K2 | 任务详情 + 日志 | 打开某已完成任务 | 失败原因摘要 + 折叠完整日志；harness 信息可见 | S |
| K3 | 创建任务选择器 | TaskFormDrawer | harness 选择器按 issue lineage 锁定/可选行为正确 | S |

---

## 4. Multi-Harness 双引擎矩阵

> 冒烟：两引擎各跑 `E1/E2` 一列；完整回归：全表。`—` 表示该场景不适用（能力为 false）。

| 场景 | claude | codex | 关键回归点 |
|---|---|---|---|
| 全流程 execute + fresh | ✅ | ✅ | `run.completed(success)`、commit+MR、真实 session_id |
| resume（continue） | ✅ | ✅ | codex 用 `codex exec resume <session>`；`CODEX_HOME` 挂 issue-shared 持久目录；`input_session` 真实 |
| 取消 | ✅ | ✅ | TERM trap → `harness.failed(cancelled)`；finalizer 的 cancelled 分支 harness 无关（Task 469/509） |
| 超时 | ✅ | ✅ | 全局 `task_timeout` → `harness.failed(timeout)`；恢复配置 |
| retry | ✅ | ✅ | bundle digest 冻结复用；Harness/Endpoint/Credential 原样复制 |
| turn-terminal 语义 | — | ✅ | **最后 turn 权威**；`turn.completed→turn.failed` = 失败（绝不猜测成功）；终态由 `codex_adapter_emit_terminal` 在流结束补发 |
| auth/rate-limit 分类 | ✅ | ✅ | `error→provider.retry`、`turn.failed→harness.failed`（401/429/sandbox）；不得降级为通用 `protocol_error` |
| context compaction | ✅ | ✅ | 多 turn 时 `context.compacted`；harness.completed 在最后 turn（幂等守卫） |
| capability 交叉校验 | ✅ | ✅ | bundle 构建拒绝 manifest 声明超出系统上界的 capability |
| sanitizer | ✅ | ✅ | 共享 `adapters/sanitize.py`；claude `sk-ant-*` + codex cookie/path/tool-id 掩码 |
| run_text / max_turns / codegraph | ✅ | — | registry/manifest/UI snapshot 三方一致（claude true，codex false） |
| session 隔离 | ✅ | ✅ | claude/codex lineage 不串；`issue.claude_session_id` 仅 claude 写 |

---

## 5. 已修复回归点快速核查清单

> 每次 worker/task 改动后、跑 Tier 1 时逐项打勾。对应 commit 见
> [`docs/reviews/2026-08-07-multi-harness-deep-review.md`](./reviews/2026-08-07-multi-harness-deep-review.md)
> 与 [`multi-harness-debugging.md`](./multi-harness-debugging.md)。

- [ ] **resume session_id 真实**：`harness-result.json` 的 `session_id` 是真实 UUID（非 `<UUID:...>` 占位符）；continue 不报 `Provided value ... is not a UUID`。
- [ ] **cancel 终态**：RUNNING 时 cancel → canonical `harness.failed(cancelled) → run.failed(cancelled)`；DB 与 replay 一致。
- [ ] **极早取消 archive**：run.started 前取消，archive 仍保留（cancel handler 不再删容器）。
- [ ] **timeout 分类**：`harness.failed(timeout)` 而非通用错误。
- [ ] **retry bundle 冻结**：retry 任务 digest == 源任务 digest。
- [ ] **codex turn-terminal**：最后 turn 权威；`turn.completed→turn.failed` 判失败。
- [ ] **capability 交叉校验**：超界声明被拒。
- [ ] **脱敏**：`error_message`/事件流无 `glpat-`、`sk-ant-` 残留。
- [ ] **失败分类**：auth/rate-limit 有 `provider.retry`/`harness.failed` 分类，不降为 `protocol_error`。
- [ ] **WorkerSettingsPanel**：enabled/default harness 字段保存后不还原。
- [ ] **codex 运行用户**：产出物 codify-owned，无需无条件 chown。

---

## 6. 数据一致性核查（§3 G1 脚本）

```bash
tar xzf /tmp/task-<id>.tar.gz event.jsonl harness-result.json
python3 - <<'PY'
import json
lines=[l for l in open('event.jsonl') if l.strip()]
seqs=[json.loads(l)['seq'] for l in lines]
assert all(json.loads(l)['schema']=='codify.worker.event/v1' for l in lines)
assert seqs==list(range(1,len(lines)+1)), "seq 必须连续无缺口无重复"
types=[json.loads(l)['type'] for l in lines]
assert types.count('run.completed')+types.count('run.failed')==1, "只能有一个 Task terminal"
assert types[-1] in ('run.completed','run.failed'), "Task terminal 必须最后出现"
assert 'worker.finalization' in types
print("canonical OK:", len(lines), "events, terminal =", types[-1])
PY
```

三方一致：**DB task.status == canonical 终态 == replay 结果**。任何不一致即为 P1 缺陷，走 §9 流程。

---

## 7. 执行记录模板

> 每次回归复制一份到 `docs/reviews/`（或受控记录处），保留真实 commit 与结果，供下次对比。

| 日期 | 分支/HEAD | 目标 Host | 触发改动 | Tier | 结果 | 失败项(#) | 备注 |
|---|---|---|---|---|---|---|---|
| 2026-08-08 | v2 @ e19c891c | 192.168.50.129 | 冒烟基线 | 1 | ✅ | — | — |

```text
[ ] Tier 1 双 harness happy path（E1/E2）
[ ] resume 一条（H1）
[ ] MR + archive + sanitize（F1/F2/G1–G3）
[ ] §5 回归点清单
[ ] Tier 2 §3 全矩阵 + §4 双引擎故障路径（完整回归时）
[ ] §6 数据一致性
```

---

## 8. 清理与安全

- 删除 `/tmp/codify_cookies.txt`、`/tmp/task-*.tar.gz`、解压出的 `event.jsonl`/`harness-result.json`。
- 恢复被临时修改的配置（重点：`task_timeout` 必须恢复为原值，默认 1800，部分环境 3700）。
- 清理测试产生的持久工作区（`DELETE /api/tasks/{id}/workspace`）与可选的测试分支/MR。
- **真实 GitLab 警告**：回归只允许在隔离测试环境执行；测试可能创建任务、分支、MR、Issue 评论，
  不要对着正式环境运行。
- 敏感信息（Host 地址、token、私有仓库 URL、真实日志）不写入提交到 Git 的文档/证据。

---

## 9. 缺陷处置

1. 失败任务先**下载 archive**，看 `harness-events/<harness>.jsonl`（CLI 层第一现场）与 `harness-result.json`（canonical 权威）。
2. 对照 §6 判定是 DB 侧、canonical 侧还是 CLI 侧不一致。
3. 按分层触发清单决定修复后重跑 Tier 1 还是完整 Tier 2。
4. 发现的新回归点按 review 工作流记录进 §5 清单，保证下次不再漏查。
