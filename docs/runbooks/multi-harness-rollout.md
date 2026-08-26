# Multi-Harness V2 dual-canary 与生产验收 Runbook

> 配套证据模板：[multi-harness-rollout-evidence.md](multi-harness-rollout-evidence.md)
> 上级计划：[2026-08-01-multi-harness-engine-roadmap.md](../superpowers/plans/2026-08-01-multi-harness-engine-roadmap.md)
> 当前范围（2026-08-24）：V2 dual-canary；仅在显式 release overlay、冻结 identity/evidence 和
> L3/L4 门禁满足后推进。2026-08-05 的 Claude/Codex V1 直接切换演练仅保留为历史参考，不代表当前发布策略。

## 1. 适用范围与行为边界

本 Runbook 覆盖 V2 dual-canary 下的四个 Harness：Pi、OpenCode、Claude、Codex，以及从源码/制品校验
到 Docker Host 验收的推进流程。基础 Compose 保留 legacy V1 execution path；只有显式 V2 release
overlay 提供 V2 release lock 并允许 V2 execution。`v2_only` 才会拒绝 V1 contract。操作过程中：

- 不新增协议能力、不升级 CLI、不修改 Adapter 映射、不引入新的沙箱模式。
- 发现任何缺陷立即停止切换，回到 Phase 2 修复并重新生成完整制品，再重新走 3.1–3.5。
- 真实 Host 名称、内部地址、token、私有仓库 URL 和敏感日志不得写入 Git；Git 只保留脱敏模板。
- 切换窗口内不允许旧 Kit/旧镜像任务在途；运行中和已创建 Task 不做热切换，Snapshot 不修改。

## 2. 发布冻结清单

进入安装前，逐项记录并冻结。以下字段是当前 V2 release candidate 的必填证据模板；不得把历史演练
的 tag、digest 或 Harness 列表当作当前冻结值。每个启用 Harness 都必须有独立的 exact identity
与 verification evidence。

| 冻结项 | 当前 V2 dual-canary 必填值 | 生产切换时 |
|---|---|---|
| Backend/Frontend image | 发布批次 tag、repo digest、image ID、Linux platform | 重新记录并与 Profile/Task Snapshot 比对 |
| Database migration head | 发布批次的唯一 migration owner 与已审 revision | 以实际发布批次为准 |
| Worker Kit | kit version、platform、kit identity（manifest SHA-256）、archive SHA-256、构建选择集与四 key availability/reason_code | 重新记录并逐 Host 校验 kit identity |
| Runtime image identity | daemon、repo@digest、image ID、Linux platform（不含任何 CLI lock） | 三项必须与 Profile、Bundle、Host 实际值一致 |
| Kit harness inventory | `pi`、`opencode`、`claude`、`codex` 逐 key：availability 与 absent reason_code；present CLI 的 exact path/version/SHA-256 | 仅对 present key 逐 Harness 重新校验；absent 记录 reason，不伪造证据 |
| Runtime Bundle/evidence | 每个 Harness 独立 Task snapshot、bundle digest、adapter version+digest、identity/evidence/platform | 以 DB-bound Bundle 与 verification evidence 为准 |
| 协议 | Runtime contract `codify.worker.harness/v2`、Canonical Event `codify.worker.event/v1`、orchestration `1.0.0` | 不变量 |
| Profile payload | `HARNESS_EXECUTION_MODE=dual_canary`；`enabled_harnesses=["pi","opencode","claude","codex"]`；V2 identity/evidence 完整 | 以生产 Profile snapshot 为准 |
| 凭据交付 | 每个 Harness/Provider 的 `credential_ref`、权限边界、轮换记录与风险接受文档 | 逐 Profile/Provider 复核 |
| 回滚坐标 | 当前稳定 legacy V1 Profile、Kit、runtime image 和 migration compatibility window | 发布前记录并保留 |

冻结后任何一项改变都必须产生新的 release candidate 和证据批次。

## 3. Host 与 Profile 部署矩阵

对每个可被 Worker Profile 选中的 Docker daemon 记录：逻辑名称、CPU 架构、Docker 版本、连接方式、
Kit 安装根、runtime images、私有 CA、网络出口类别、旧稳定 Profile、目标 Profile、回滚负责人。

| Host alias | Arch | Docker | 连接 | Kit 根 | Runtime images | CA | 网络出口 | 旧 Profile | 目标 Profile | 回滚负责人 |
|---|---|---|---|---|---|---|---|---|---|---|
| `<host-a>`（dev 演练） | `x86_64` | `28.5.2` | daemon `tcp` + ssh context | `/opt/codify/worker-kits` | `codify-worker/java21-maven:2026.07` | `/opt/ca.crt` | 可达 DeepSeek/GitLab | `worker kit` tag 坐标 | `worker kit` digest 坐标 | `<owner>` |
| `<host-b>` | 按实际 | 按实际 | 按实际 | 按实际 | 按实际 | 按实际 | 按实际 | 按实际 | 按实际 | `<owner>` |

要求：

- 每个目标 Profile 唯一映射 daemon、Kit path、image digest、Harness binary 和凭据策略。
- 标记需要 amd64/arm64 Kit 和 CLI binary 的 Host，禁止跨架构复用制品。
- 通过实际 Docker context/daemon 检查确认路径和镜像属于远程 Host，不把 Backend 本机路径当成 daemon host 路径。
- 记录 Provider 可达性；某 Host 不能访问某 Endpoint 时，不把它加入对应 Profile 路由。

## 4. 逐 Host 安装与验证

### 4.1 制品校验

```bash
make worker-kit-export WORKER_KIT_VERSION=<release-version> WORKER_KIT_PLATFORM=linux/amd64 \
  WORKER_KIT_HARNESSES='<pi opencode>'      # 默认集合；显式子集或空集合亦可
make worker-kit-export WORKER_KIT_VERSION=<release-version> WORKER_KIT_PLATFORM=linux/arm64 \
  WORKER_KIT_HARNESSES='<pi opencode>'
make offline-bundle-export WORKER_KIT_VERSION=<release-version>
```

导出后必须校验 archive SHA-256、kit identity（manifest SHA-256 加 canonical full-content inventory）、
构建选择集与 manifest 四 key availability/reason 的一致性（未选择 → `not_selected`；选中但缺 payload
→ `missing_payload` 且 Kit degraded）、Runtime Bundle Adapter 文件/digest、golden fixture smoke，并在隔离临时目录做一次
全新安装演练，确认安装器拒绝覆盖既有 kit identity 目录。

### 4.2 安装

在 daemon Host 上安装到新版本路径，禁止覆盖旧目录：

```bash
sudo ./scripts/install-worker-kit.sh \
  kits/codify-worker-kit-<release-version>-linux-amd64-<manifest-prefix>.tar.gz
```

加载 runtime images 并用 digest 检查实际内容；保留旧 Kit 安装目录和旧 runtime image。

### 4.3 逐 Harness 离线 verify-runtime

在 daemon Host 侧执行（Kit path 与 host binary path 都是 daemon Host 路径）：

```bash
make worker-kit-verify \
  KIT_PATH=/opt/codify/worker-kits/<release-version>-linux-amd64 \
  RUNTIME_IMAGE=<runtime-image> \
  RUNTIME_MANIFEST=/srv/codify/releases/<release>/frozen-runtime-manifest.v2.json \
  VERIFY_ALL_HARNESSES=1 \
  SMOKE='java -version && mvn -version'
```
`VERIFY_ALL_HARNESSES=1` is the release gate: it iterates the Runtime Bundle adapters, checks the
Kit contract/event compatibility and image platform, verifies Kit inventory integrity for every
key (absent key 不得残留 payload/path；present key 校验 path/权限/可执行性/self-integrity SHA)，
runs the functionality gate（`--version`、self-check、Adapter smoke）仅对 present key，并把
observed vs Adapter baseline 的 version/SHA 差异记录为脱敏 advisory warning——差异不阻断。
It does not treat the Kit manifest as a Runtime Bundle manifest. A normal Profile/API
verification remains one `default_harness_key` at a time and may omit `RUNTIME_MANIFEST`; that
preserves the historical installation-preflight boundary. The path may be a release-stamped
`codify.worker.runtime-manifest/v2` document or a DB-persisted `codify.worker.runtime-bundle/v2`
document that retains each nested Adapter identity. Do not pass a Kit manifest, a container-only
Launcher flat projection, or the repository template with placeholder SHA values.
单个 present Harness functionality 失败只把该 Harness 标记 unavailable 并记录脱敏原因；其余
Harness 继续验证。选择 absent Harness 的 Profile/Task 在 API 侧得到稳定 `harness_cli_unavailable`，
不伪造验收。

For an explicit one-Harness host-mount break-glass override, use the same command with
`HARNESS_KEY`, `HARNESS_HOST_PATH`, and `HARNESS_CONTAINER_PATH`; host_mount 必须逐 Harness 显式
授权并记录来源：

```bash
make worker-kit-verify \
  KIT_PATH=/opt/codify/worker-kits/<release-version>-linux-amd64 \
  RUNTIME_IMAGE=<runtime-image> \
  HARNESS_KEY=codex \
  HARNESS_HOST_PATH=/opt/codify/codex/bin/codex \
  HARNESS_CONTAINER_PATH=/opt/codify-codex/bin/codex
```

检查 Kit harness inventory 与 integrity、kit identity、Runtime Bundle Adapter version/digest、
CLI source/path/version/binary digest（worker_kit 或已授权 host_mount）、CA、PATH、工作区写权限、
UID/GID、sandbox、Skills、Mermaid 和项目 toolchain smoke。禁止任何从 image/`PATH` 的隐式 CLI 回退。
对 remote Docker 特别验证 Host bind path、agent-state、Kit/Nix store 和 runtime bundle 均能在
daemon 侧访问。任一 Host/Harness 失败即标记不可路由，不能靠其他 Host 成功放行；absent Harness
只记录 `harness_cli_unavailable` 及 reason，不算 Host 失败。

V2 release overlay 不再注入任何 image CLI lock（`docker-compose.v2-release.yml` 已随旧链删除）。
发布只需冻结的 Kit archive（content-addressed）、Runtime Bundle 与 image identity 组合：

```bash
export WORKER_KIT_ARCHIVE=/srv/codify/releases/<release>/codify-worker-kit-<version>-linux-amd64-<sha12>.tar.gz
export V2_RELEASE_WORKER_IMAGE=codify-worker/java21-maven:<release>
deploy/scripts/preflight-v2-release.sh
```

`preflight-v2-release.sh` 通过选中 Docker daemon 校验 Kit archive 的 manifest（四 key
`harness_inventory`、availability/reason）、content digest 命名与 image identity/platform；
仅运行 `docker image inspect` 不能证明 archive 在 daemon 侧可读。Runtime Bundle bind 会冻结
`image_identity + kit_identity + bundle_digest`；逐 Harness 验收仍必须同时包含离线 verify-runtime
与一个真实 smoke Task。

### 4.4 Codify API verify-runtime

Profile 保存后，通过 Codify 路径再验证一次，确认 API 使用 Profile 固定 daemon、核对冻结的
kit identity 并持久化 `image_digest` / `verified_at`：

```http
POST /api/worker-profiles/<profile-id>/verify-runtime
Content-Type: application/json

{"smoke_command":"java -version && mvn -version"}
```

响应必须包含 `ok=true`、`image_digest`（repo digest）和 `verified_at`。Profile 更新镜像、Kit 或
Harness allowlist 后 `verified_at` 会被清空，必须重新验证。

## 5. 真实验收矩阵

### 5.1 DB-bound Runtime Bundle 归档（L3）

每个已验证 V2 Task 都在 backend 所在 Host 导出其冻结 Bundle；`BUNDLE_EXPORT_DIR` 必须是 backend 容器的
归档 bind mount，而不是笔记本上的路径。导出不会从 checkout 重建、不会下载，并以
`runtime-bundle-v2-<digest>` 目录原子发布：

```bash
make worker-runtime-bundle-export TASK_ID=<verified-task-id> BUNDLE_EXPORT_DIR=/opt/codify-archives/runtime-bundles
```

一个导出只证明该 Task snapshot 选择的 Harness/key；Pi、OpenCode、Claude、Codex 必须各有一个经过验证的
Task 和独立导出。目标目录已存在或任一身份、证据、platform、archive/manifest 校验失败即停止。该 L3
归档不能替代同一 Host 上完整 Git/MR、session、取消和回放的 L4 验收。

每个进入生产支持范围的 Harness 至少在一个目标 Host 完成，关键 Host 全部覆盖。证据模板逐行记录
Task ID、Harness、attempt ID、Host、Profile snapshot、MR/commit、archive digest、结果和人工结论。

- 新 Issue 首个 execute Task：分支、修改、提交、Push、创建/更新 MR。
- 成功但无文件变化；`require_changes` true/false 结果正确。
- 同一 Harness、同一 namespace 的后续 Task resume 成功。
- fresh session 明确不恢复旧 session。
- namespace 因 Endpoint/认证域/Adapter state 变化时显式新 lineage。
- Claude → Codex → Claude，Session 不串线且原 Claude lineage 可恢复。
- retry 继续使用原 Harness、Endpoint snapshot、image digest、Kit 和 Runtime Bundle。
- Task Skills 可发现且 `/workspace` Git diff 无 Skills 文件。
- 工具失败、Provider 认证失败、限流、网络中断和 protocol diagnostic 的失败分类正确。
- 取消、timeout、SIGTERM/KILL 能终止进程树并清理容器、Issue mutex 和工作区锁。
- Canonical Event、raw event、console、result、artifacts 可下载、清洗并离线回放。
- Git/MR、commit message fallback、delivery summary、Mermaid 和 Claude-only CodeGraph 行为正确。

## 6. Dual-canary 推进

### 6.1 前置检查

- 3.1–3.5 全部完成：Host 矩阵、制品冻结与校验、逐 Host verify-runtime、真实验收矩阵、基线指标就绪。
- 所有目标 Host 的 Kit、image digest、CLI/Adapter、CA/PATH、sandbox、workspace 和 agent-state 验证通过。
- 阻断指标为零。

### 6.2 发版硬边界

1. 关闭/处理历史 Issue；PENDING/QUEUED/RUNNING 旧任务 drain 或取消，切换窗口内无旧 Kit/旧镜像任务在途。
2. 没有 V2 Runtime Bundle 的 V2 Task 不允许执行或 retry；legacy V1 Task 继续遵循 legacy execution path。
3. 每个可调度 Host 安装并验证新 Kit；每个启用 Profile 切到冻结版本后才能恢复调度。

### 6.3 Canary 推进边界

- 仅将已完成 exact identity/evidence 和 verify-runtime 的 Harness 加入 V2 canary；其余 Harness
  继续使用 legacy V1 execution path 或保持未启用。任一 Host 未通过 verify-runtime 不得恢复 V2 调度。
- 镜像引用使用 `repo@sha256:...` 或等价不可变 ID，不依赖可变 tag 作为验收依据。
- 新 Task 在创建时冻结 Task Snapshot；运行中和已创建 Task 均不做热切换。
- 任一阻断阈值触发立即停止 V2 canary 的新 Task 创建，保留运行证据并按第 8 节回滚；不得直接
  将未完成 L3/L4 的全量 Harness 切换为 V2。

### 6.4 切换后 smoke

dual-canary 阶段为 Pi、OpenCode、Claude、Codex 分别创建 smoke Task，验证完整 Git/MR、session、
cancel/timeout 和归档回放链路；每个 smoke 必须落在 digest 与 evidence 固定后的 Profile 上。

## 7. 指标、阈值与告警

推进前记录 legacy V1 execution baseline；dual-canary 中按 Harness/Adapter/CLI/Profile/Host 观察，避免聚合掩盖单 Host 问题。
现有入口：

- `GET /api/analytics?days=30`：响应 `harnesses[]` 已按 harness_key/adapter_version 聚合成功率、失败率、
  取消率、耗时。
- `GET /api/stats` / `/api/stats/...`：队列压力、Worker 对齐、失败率等系统级指标。
- `PATCH /api/config/runtime`：`alert_on_failure` + `alert_webhook_url` 失败告警入口。
- 运维查询（SQL/只读副本）：按 `task_worker_profile_snapshots.harness_key`、
  `cli_version`、`docker_host`、`runtime_bundle_digest`、`image_digest` 分片统计。

建议阻断阈值（任意一项触发立即停新任务）：

| 指标 | 阈值 |
|---|---|
| 错误成功判定（success 但无变更/无事件/无 commit） | `> 0` |
| session 串线（跨 Harness 复用或跨 namespace 续跑） | `> 0` |
| 凭据泄漏（raw 日志/告警含 secret 形态） | `> 0` |
| 无法取消（cancel 后超时未终态） | `> 0` |
| 双 Task terminal / seq 缺口 | `> 0` |

切换后观察阈值（由发布负责人按基线与容量批准）：

| 指标 | 建议阈值 |
|---|---|
| 成功率 | 不低于切换前基线 |
| P95 耗时 | 不超过基线 × 1.5 |
| rate limit / provider 429 | 不超过基线 × 1.5 |
| sandbox failure | `> 0` 即阻断 |
| protocol error | 不超过基线 × 1.5 |
| capability warning | 记录并按影响分类 |
| runtime verification stale | Profile `verified_at` 过期即阻断 |

设置最小观察任务数和观察时间，样本不足不认定切换成功。日志/归档告警内容必须先清洗，不能把 raw
Provider 响应直接发送到外部通知。

## 8. 回滚

1. 回滚把所有启用 Profile 和新 Task 分配恢复到旧稳定 Profile/Kit；不把既有 Issue 或 Task 路由改写到旧 Profile。
2. 切换后已运行新 Kit 的 Issue 如必须继续工作，停止在原 Issue 创建 Task，创建关联 replacement Issue
   并在创建时选择旧稳定 Profile；保留原 Issue、Task、Session 和证据链，不复制跨 Profile/Harness session ID。
3. 运行中和已创建 Task 的 Snapshot 不修改、不强制切 Harness；是否允许其自然完成或取消由阻断指标级别决定并记录。
4. 验证旧 Backend/Frontend 与新增数据库字段的兼容窗口；数据库 downgrade 不是默认回滚手段。
5. 演练新 Kit 验证失败、Codex Provider 不可达、单 Host 故障和 canonical protocol error 上升四种场景。
6. 确认旧 Kit path、runtime image、Profile 和 Provider credential 仍可用。
7. 回滚后新建一个使用旧稳定 Profile 的 Issue，再创建 legacy V1 smoke Task，验证 Issue 分配与完整执行路径恢复。

## 9. 生产签署

每个 Host/Harness 的安装、验证、smoke、切换、指标和回滚证据汇总到证据模板，逐项签署后：

- 所有目标 Host 与启用 Profile 已切换到冻结版本，稳定观察期指标在批准阈值内。
- 切换已成功回滚演练到旧 Profile/Kit，replacement Issue 流程通过，且未修改既有 Issue Profile 或 Task Snapshot。
- 证据能区分源码测试、制品安装、真实 smoke 和切换结果。
- 运维 runbook、Host 清单、告警和责任人已完成交接。

达到以上条件后，四个 Harness 才可分别标记为生产基线；未满足某 Harness 的 L3/L4 门禁时，继续保持
该 Harness 的 legacy V1 execution path 或未启用状态，不得宣称已完成全量切换。

### 9.1 历史参考：2026-08-05 Claude/Codex V1 演练

旧演练中的 Claude/Codex 版本、digest、Profile payload 与“全部目标 Host 验证后直接切换”文字，
只用于解释历史证据格式，不是当前冻结值、当前 Harness 范围或当前发布策略。当前仍需遵守基础 Compose
保留 legacy V1 execution path、显式 V2 overlay、逐 Harness exact identity/evidence，以及 L3（制品绑定）和 L4（真实
Docker Host 执行）分层门禁。
