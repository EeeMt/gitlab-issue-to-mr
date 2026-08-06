# Multi-Harness 直接切换与生产验收 Runbook

> 配套证据模板：[multi-harness-rollout-evidence.md](multi-harness-rollout-evidence.md)
> 上级计划：[2026-08-01-multi-harness-engine-roadmap.md](../superpowers/plans/2026-08-01-multi-harness-engine-roadmap.md)
> 修订（2026-08-05）：取消 canary/灰度，全部目标 Host 验证完成后直接切换。

## 1. 适用范围与行为边界

本 Runbook 只覆盖 Claude + Codex 双引擎生产切换。操作过程中：

- 不新增协议能力、不升级 CLI、不修改 Adapter 映射、不引入新的沙箱模式。
- 发现任何缺陷立即停止切换，回到 Phase 2 修复并重新生成完整制品，再重新走 3.1–3.5。
- 真实 Host 名称、内部地址、token、私有仓库 URL 和敏感日志不得写入 Git；Git 只保留脱敏模板。
- 切换窗口内不允许旧 Kit/旧镜像任务在途；运行中和已创建 Task 不做热切换，Snapshot 不修改。

## 2. 发布冻结清单

进入安装前，逐项记录并冻结。以下数值是 2026-08-05 在 dev 目标 Host 完成演练时的 release candidate
证据，生产切换必须以实际发布批次重新冻结并填入证据模板。

| 冻结项 | 冻结值（2026-08-05 dev 演练） | 生产切换时 |
|---|---|---|
| Backend image | `codify-backend:latest`，content digest `sha256:00e992eb8f99d0c6756e8aa8cc20bffdf17cfad1962647264064df447d5fa669`，repo `127.0.0.1:5000/codify-backend@sha256:37671703a81492c0f578c753ce8599bdf670d54c1cd5ba0c97b793d2edd5ec90` | 重新记录 repo digest |
| Frontend/Nginx image | `codify-nginx:latest`，content digest `sha256:74324ed288483b8003224abd8b71670af8c86228a3bc00421be232af863949e2`，repo `127.0.0.1:5000/codify-nginx@sha256:bf65cf01c9886b97a448af1b476696039272a75e2014e82673238acb336bafe7` | 重新记录 repo digest |
| Database migration head | `065_worker_profile_verification` | 以发布时实际 head 为准 |
| Worker Kit | `0.3.10`；amd64 archive `48880f314d0c380333b932771b7c0f09628d2093a6396167925ea94bbc1b96b1`；manifest `97b316b509f5b2608684fe505cf88f5a9a121680210727b08d4f83c463af011e` | 重新记录 archive/manifest SHA-256 |
| arm64 Kit | 当前 Host 矩阵无 arm64 Host，标记 not required；新增 arm64 Host 前必须导出并校验，禁止跨架构复用 | 按矩阵标记 |
| Runtime image | `codify-worker/java21-maven:2026.07`，content digest `sha256:9e2981c4835156bc05b451730091de6389cd4f3688345c9b331ccf2012f20a11`，repo `127.0.0.1:5000/codify-worker/java21-maven@sha256:a9d046b1382eaf0574d88754bef916199317a7b5becba9b10be75440508461e3` | 重新记录 repo digest |
| Claude CLI | `2.1.153`，binary `sha256:214f603f31942162dac9a65f18d43b3ac646ae215240fad481c4aad6c60f2e38`，source `image`/host mount `/usr/local/bin/claude` | 重新校验 |
| Codex CLI | `0.146.0`，binary `sha256:2e863156ed35ecc5253b1e2f907a9143077b9f7cb51942070c61996471ff6e04`，source `host_mount` `/opt/codify-codex/bin/codex` | 重新校验 |
| Runtime Bundle | Task Snapshot `runtime_bundle_digest=00addfc6f57be75f70f3ce1eb9591e60c15e7e32dfcece75d2e32884248c5a59`；Claude Adapter `1.0.1`，Codex Adapter `1.0.0`，Adapter digest `80dc16c0dd0092514758ac998652420abee96ac9da358530037b5dce736bb595` | 以发布批次 manifest 为准 |
| 协议 | Runtime contract `codify.worker.harness/v1`，Canonical Event `codify.worker.event/v1`，orchestration `1.0.0` | 不变量 |
| Profile payload | Profile 11 `worker kit`：`runtime_mode=mounted_kit`、Kit `0.3.10`、`enabled_harnesses=["claude","codex"]`、`default_harness_key=claude`、image digest 固定为上述 repo digest、sandbox `container-boundary`、`approval_policy=never`、codex execpolicy 禁 git 写操作 | 以生产 Profile 为准 |
| 凭据交付 | 受限 legacy 容器密钥 + `docs/security/credential-delivery-risk-acceptance.md`；`credential_ref` 运行时接线延后 | 书面风险接受已签署 |
| 回滚坐标 | Profile 1 `Default Worker`（legacy baked，保留）；Kit `0.3.9-linux-amd64` 保留在 Host；切换前 Profile 11 的 image tag 坐标已记录 | 保留旧目录/旧镜像 |

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
make worker-kit-export WORKER_KIT_VERSION=<release-version> WORKER_KIT_PLATFORM=linux/amd64
make worker-kit-export WORKER_KIT_VERSION=<release-version> WORKER_KIT_PLATFORM=linux/arm64
make offline-bundle-export WORKER_KIT_VERSION=<release-version>
```

导出后必须校验 archive SHA-256、manifest SHA-256、Runtime Bundle Adapter 文件/digest、golden fixture
smoke，并在隔离临时目录做一次全新安装演练，确认安装器拒绝覆盖已有版本目录。

### 4.2 安装

在 daemon Host 上安装到新版本路径，禁止覆盖旧目录：

```bash
sudo ./scripts/install-worker-kit.sh \
  kits/codify-worker-kit-<release-version>-linux-amd64.tar.gz
```

加载 runtime images 并用 digest 检查实际内容；保留旧 Kit 安装目录和旧 runtime image。

### 4.3 逐 Harness 离线 verify-runtime

在 daemon Host 侧执行（Kit path 与 host binary path 都是 daemon Host 路径）：

```bash
./scripts/verify-worker-runtime.sh \
  --kit /opt/codify/worker-kits/<release-version>-linux-amd64 \
  --image <runtime-image> \
  --harness-key claude \
  --harness-host-path /usr/bin/claude \
  --harness-container-path /usr/local/bin/claude \
  --smoke 'java -version && mvn -version'

./scripts/verify-worker-runtime.sh \
  --kit /opt/codify/worker-kits/<release-version>-linux-amd64 \
  --image <runtime-image> \
  --harness-key codex \
  --harness-host-path /opt/codify/codex/bin/codex \
  --harness-container-path /opt/codify-codex/bin/codex \
  --smoke 'test -x /opt/codify-codex/bin/codex && /opt/codify-codex/bin/codex --version'
```

检查 Kit compatibility manifest、Runtime Bundle Adapter version/digest、CLI source/path/version/binary
digest、CA、PATH、工作区写权限、UID/GID、sandbox、Skills、Mermaid 和项目 toolchain smoke。
对 remote Docker 特别验证 Host bind path、agent-state、Kit/Nix store 和 runtime bundle 均能在
daemon 侧访问。任一 Host/Harness 失败即标记不可路由，不能靠其他 Host 成功放行。

Kit 只包含 bootstrap 与验证工具，不包含执行 Adapter；`--verify` 的逐 Harness 检查通过 smoke 覆盖
CLI 存在性/版本，Adapter 级别的 binary digest/version/config 校验由 Task 容器启动时以冻结的
Runtime Bundle 执行（`CODIFY_CLI_BINARY_DIGEST`）。因此逐 Harness 验收必须同时包含离线
verify-runtime 与一个真实 smoke Task。

### 4.4 Codify API verify-runtime

Profile 保存后，通过 Codify 路径再验证一次，确认 API 使用 Profile 固定 daemon 并持久化
`image_digest` / `verified_at`：

```http
POST /api/worker-profiles/<profile-id>/verify-runtime
Content-Type: application/json

{"smoke_command":"java -version && mvn -version"}
```

响应必须包含 `ok=true`、`image_digest`（repo digest）和 `verified_at`。Profile 更新镜像、Kit 或
Harness allowlist 后 `verified_at` 会被清空，必须重新验证。

## 5. 真实验收矩阵

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

## 6. 直接切换

### 6.1 前置检查

- 3.1–3.5 全部完成：Host 矩阵、制品冻结与校验、逐 Host verify-runtime、真实验收矩阵、基线指标就绪。
- 所有目标 Host 的 Kit、image digest、CLI/Adapter、CA/PATH、sandbox、workspace 和 agent-state 验证通过。
- 阻断指标为零。

### 6.2 发版硬边界

1. 关闭/处理历史 Issue；PENDING/QUEUED/RUNNING 旧任务 drain 或取消，切换窗口内无旧 Kit/旧镜像任务在途。
2. 无 Runtime Bundle 的 Task 只读，不允许执行或 retry。
3. 每个可调度 Host 安装并验证新 Kit；每个启用 Profile 切到冻结版本后才能恢复调度。

### 6.3 一次性直接切换

- 把所有启用 Worker Profile 切到冻结 Kit、image digest、harness allowlist/约束和凭据策略；
  任一 Host 未通过 verify-runtime 不得恢复调度。
- 镜像引用使用 `repo@sha256:...` 或等价不可变 ID，不依赖可变 tag 作为验收依据。
- 新 Task 在创建时冻结 Task Snapshot；运行中和已创建 Task 均不做热切换。
- 任一阻断阈值触发立即停止新 Task 创建，保留运行证据并按第 8 节回滚。

### 6.4 切换后 smoke

切换后立即创建 Claude + Codex smoke Task，验证完整 Git/MR、session、cancel/timeout 和归档回放链路；
每个 smoke 必须落在 digest 固定后的 Profile 上。

## 7. 指标、阈值与告警

切换前记录旧 Claude 基线；切换后按 Harness/Adapter/CLI/Profile/Host 观察，避免聚合掩盖单 Host 问题。
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
7. 回滚后新建一个使用旧稳定 Profile 的 Issue，再创建 Claude smoke Task，验证 Issue 分配与完整执行路径恢复。

## 9. 生产签署

每个 Host/Harness 的安装、验证、smoke、切换、指标和回滚证据汇总到证据模板，逐项签署后：

- 所有目标 Host 与启用 Profile 已切换到冻结版本，稳定观察期指标在批准阈值内。
- 切换已成功回滚演练到旧 Profile/Kit，replacement Issue 流程通过，且未修改既有 Issue Profile 或 Task Snapshot。
- 证据能区分源码测试、制品安装、真实 smoke 和切换结果。
- 运维 runbook、Host 清单、告警和责任人已完成交接。

达到以上条件后，Claude + Codex 才标记为生产基线。OpenCode 保持未启动，至少等待一个稳定 Worker Kit
发布周期后再评估 Phase 4 准入。
