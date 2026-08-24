# 生产环境部署指南

本文档面向运维和部署人员，说明如何在长期运行的环境中部署 Codify（Codify），以及如何安全地更新、备份和排障。

## 1. 部署目标与架构

默认部署方式基于 `deploy/docker-compose.yml`，会启动 4 个核心服务：

- `postgres`：持久化任务、配置、用户、会话和审计数据
- `backend`：HTTP API 与 Dashboard 后端
- `scheduler`：任务调度与崩溃恢复
- `nginx`：前端静态资源与反向代理入口

当前 compose 约定：

- `backend` 与 `scheduler` 共用 `codify-backend:latest`
- `backend` 与 `scheduler` 均固定 `AUTO_MIGRATE=false`
- migration 只由维护窗口内一次性的 `migrate` profile 执行
- `HARNESS_EXECUTION_MODE` 必须显式设置为 `dual_canary` 或 `v2_only`
- PostgreSQL 数据挂载在 Docker volume `postgres_data`

## 2. 部署前准备

### 2.1 基础依赖

请确认目标主机满足以下条件：

- 已安装 Docker 和 Docker Compose
- 可访问目标 GitLab 实例
- 可访问四个 Harness 的兼容模型服务（Pi/OpenCode/Claude/Codex）
- Docker Engine 允许当前部署方式所需的 Worker 容器启动能力

### 2.2 关键配置项

`deploy/docker-compose.yml` 当前通过 `deploy/.env.test` 为 `backend` 和 `scheduler` 注入环境变量。生产环境至少需要准备以下配置：

#### GitLab

- `GITLAB_URL`
- `GITLAB_BOT_TOKEN`

#### 模型服务

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`

#### 应用安全

- `SECRET_KEY`
- `CONFIG_ENCRYPTION_KEY`

#### 调度与 Worker

- `WORKER_IMAGE`
- `MAX_CONCURRENCY`
- `TASK_TIMEOUT`
- `SCHEDULER_INTERVAL`
- `DEFAULT_TARGET_BRANCH`
- `HARNESS_EXECUTION_MODE`（验证阶段使用 `dual_canary`；硬切验收通过后才使用 `v2_only`）

#### 可选认证配置

- OIDC 相关基础环境项（如果你的部署方案仍通过环境变量提供一部分默认值）
- Break-glass 相关环境变量（如果启用紧急登录）

## 3. 持久化与数据安全

这是生产部署里最重要的一条：

- 运行时配置、OIDC 配置、用户、会话、审计日志都保存在 PostgreSQL 中
- Dashboard 中通过 `/configuration` 页面录入的敏感配置会加密后落到数据库
- 如果 PostgreSQL volume 被删除，以上数据会一并丢失

因此请避免在生产环境执行以下操作：

```bash
docker-compose down -v
```

这个命令会删除 volume，等价于重置数据库。

建议至少建立以下备份策略：

- 定期导出 PostgreSQL 数据库
- 定期备份 Docker volume 或底层磁盘快照
- 对 `deploy/.env.test` 或对应的正式环境变量来源做安全备份
- 单独保留 OIDC Client Secret、Break-glass 配置等恢复材料

## 4. 首次部署流程

### 4.1 准备配置文件

在 `deploy/` 目录准备环境变量文件，例如：

```bash
cd deploy
cp .env.test .env.production
```

然后将 `docker-compose.yml` 中 `env_file` 指向你的正式配置文件，或者直接维护现有文件名。

至少确认以下两类密钥已替换为正式值：

- `SECRET_KEY`
- `CONFIG_ENCRYPTION_KEY`

如果这两个值不稳定或被重置，会影响会话和配置解密。

### 4.2 唯一 migration owner

先备份数据库并确认要执行的 Alembic revision，不允许 Backend、Scheduler 或两个副本竞争执行迁移，
也不要在维护窗口使用会漂移的 `head`：

```bash
cd deploy
export HARNESS_EXECUTION_MODE=dual_canary
export MIGRATION_TARGET=<reviewed_revision>
docker compose up -d postgres
docker compose --profile maintenance run --rm migrate
```

物理 V2 schema 变更是 roll-forward-only。迁移后如果启动验证失败，应部署已评审的向前修复 revision，
不得重新启动依赖旧物理 schema 的 V1 Backend/Scheduler。

### 4.3 构建并启动服务

在仓库根目录执行：

```bash
cd deploy
HARNESS_EXECUTION_MODE=dual_canary docker compose up -d --build backend scheduler nginx
```

启动后建议检查：

```bash
docker compose ps
docker compose logs --tail 100 backend
docker compose logs --tail 100 scheduler
docker compose logs --tail 100 nginx
```

### 4.4 健康检查

默认端口：

- 前端：`http://<host>:8880`
- 后端：`http://<host>:8000`

可先检查后端健康接口：

```bash
curl -f http://<host>:8000/health
deploy/scripts/preflight-execution-mode.sh http://<host>:8000/health http://<host>:8001/health
```

再访问前端首页确认 Dashboard 可打开。

## 5. 上线后的初始化配置

### 5.1 OIDC 登录

建议在服务基础可用后，再通过 Dashboard 配置 OIDC：

1. 初次部署先保持 OIDC 关闭
2. 登录 Dashboard（如果已有入口）
3. 打开 `/configuration`
4. 填写 OIDC 参数
5. 使用内置测试与诊断页面验证
6. 验证通过后再启用 OIDC

详细步骤见 [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)。

### 5.2 Break-glass 紧急入口

如果生产环境启用了 break-glass：

- 仅在紧急恢复时开启
- 使用后尽快关闭
- 定期验证审计日志是否记录正常

不要把 break-glass 凭据放进数据库或提交到仓库。

## 6. 日常发布与重建

### 6.1 后端 / 调度器代码更新

当 `backend/`、调度逻辑或 API 变更时：

```bash
docker build -f deploy/Dockerfile.backend -t codify-backend:latest .
cd deploy && docker-compose up -d backend scheduler
```

说明：

- `backend` 与 `scheduler` 共用同一个镜像
- 如果只重启其中一个，容易出现代码版本不一致

### 6.2 前端代码更新

当 `frontend/` 变更时：

```bash
cd frontend && npm run build
cd ../deploy && docker-compose build nginx && docker-compose up -d nginx
```

### 6.3 Worker 镜像更新

当 Worker 执行环境变更时，例如：

- `deploy/Dockerfile.worker-java21-maven`
- Worker 内依赖工具
- Claude 执行环境

V2 Worker image 必须把四个 CLI 的**精确版本和 executable SHA-256**写入镜像内
`/etc/codify-worker-cli-artifacts.json`。`deploy/worker-cli/` 是本机构建输入，已被 Git
ignore；只放二进制及其运行所需资源，绝不放 Provider token、`.env` 或凭据。

先在受控构建机对已审核 payload 计算 digest（这些值不是秘密）：

```bash
sha256sum deploy/worker-cli/pi/bin/pi deploy/worker-cli/opencode/opencode \
  deploy/worker-cli/claude deploy/worker-cli/codex/bin/codex
```

再显式传入四个 digest 构建。任何一个缺失、可执行文件不匹配、版本不匹配或目标平台不一致都会让构建失败：

```bash
make worker-runtime-image-build \
  WORKER_KIT_PLATFORM=linux/amd64 \
  RUNTIME_IMAGE=codify-worker/java21-maven:<release> \
  PI_CLI_SHA256=<64-hex> \
  OPENCODE_CLI_SHA256=<64-hex> \
  CLAUDE_CLI_SHA256=<64-hex> \
  CODEX_CLI_SHA256=<64-hex>
```

导出镜像实际写入的不可变 CLI identity 文档到受控发布目录（拒绝覆盖既有 lock）：

```bash
make worker-cli-artifact-export \
  RUNTIME_IMAGE=codify-worker/java21-maven:<release> \
  CLI_ARTIFACT_MANIFEST=/srv/codify/releases/<release>/worker-cli-linux-amd64.json
```

V2 release 使用单独 Compose overlay 将这个**只读、非 secret**文件以相同固定容器路径提供给
Backend 和 Scheduler；基础 `docker-compose.yml` 保留 dual-canary 的 legacy V1 execution path，
不会为它创建空的 V2 release-lock bind mount：

```bash
export CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH=/srv/codify/releases/<release>/worker-cli-linux-amd64.json
export CODIFY_V2_RELEASE_WORKER_IMAGE=codify-worker/java21-maven:<release>
deploy/scripts/preflight-v2-release.sh
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.v2-release.yml config --quiet
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.v2-release.yml up -d backend scheduler
```

overlay sets `CODIFY_WORKER_CLI_ARTIFACT_MANIFEST=/run/codify/worker-cli-artifacts.json` for
both services and mounts the host file there read-only. Do not put this manifest in a secret store:
it contains release identity/version/SHA metadata, not credentials.
`CODIFY_WORKER_CLI_ARTIFACT_MANIFEST_HOST_PATH` must be an absolute path on the selected Docker
**daemon Host**. With remote Docker, first copy the reviewed lock to that Host and then give the
same daemon-visible path to the Compose control host; a file only on the control host is not a bind
source. `CODIFY_V2_RELEASE_WORKER_IMAGE` must name the reviewed Worker image on that same daemon.
`preflight-v2-release.sh` runs one-shot Backend and Scheduler containers through the selected
Compose context and validates the actual read-only daemon bind and the lock/image platform match.
`docker compose ... config` checks only interpolation and cannot prove the daemon can see the path.

新 V2 Runtime Bundle bind 会从该 lock 写入每个 Adapter 的 artifact SHA 与目标平台；源 Runtime manifest 中的
占位符不能替代它。一个 Bundle 对应一个发布的 image/platform identity，因此多架构部署应分别构建、
导出、审查并为相应调度域使用正确 lock，不能混用 amd64 与 arm64 文档。

完成 Kit 安装后，使用显式 Runtime manifest 验证四个 Harness：

```bash
make worker-kit-verify \
  KIT_PATH=/opt/codify/worker-kits/<kit-release>-linux-amd64 \
  RUNTIME_IMAGE=codify-worker/java21-maven:<release> \
  RUNTIME_MANIFEST=/srv/codify/releases/<release>/frozen-runtime-manifest.v2.json \
  VERIFY_ALL_HARNESSES=1 \
  SMOKE='java -version && mvn -version'
```

`RUNTIME_MANIFEST` 必须是 release lock 已写入 artifact SHA 的冻结
`codify.worker.runtime-manifest/v2` 文档，或数据库持久化且保留嵌套 Adapter identity 的
`codify.worker.runtime-bundle/v2` 文档；不能传入 Kit manifest、placeholder source template 或容器 Launcher 的
flat projection。此命令只是 L1/L2 source/image/Kit verification；随后仍需按 Profile 调用 API verify-runtime，并在真实
Docker Host 上完成最小 Task/MR smoke 后才有 L3/L4 证据。若 `WORKER_IMAGE` 使用其他 tag/digest，
必须同步更新 Profile 并重新验证。

## 7. 常见运维检查

### 7.1 查看服务日志

```bash
cd deploy
docker-compose logs -f backend
docker-compose logs -f scheduler
docker-compose logs -f nginx
```

### 7.2 查看数据库中的任务状态

```bash
docker exec codify-postgres psql -U codify -d codify -c \
  "SELECT id, status, error_message FROM tasks ORDER BY id DESC LIMIT 10;"
```

### 7.3 查看最近任务日志

```bash
docker exec codify-postgres psql -U codify -d codify -c \
  "SELECT task_id, level, message, created_at FROM task_logs ORDER BY id DESC LIMIT 20;"
```

### 7.4 检查 GitLab 回写结果

可以使用 GitLab API 查看 issue note / MR 内容是否已被正常更新。

## 8. 故障排查建议

### 8.1 Dashboard 打不开

优先检查：

- `nginx` 是否启动
- `backend` 是否健康
- 浏览器访问的 URL 是否指向前端端口 `8880`

### 8.2 任务创建成功但不执行

优先检查：

- `scheduler` 是否运行
- `MAX_CONCURRENCY` 是否被设得太低
- 数据库中任务是否停留在 `PENDING` / `QUEUED`
- 是否存在同一 Issue 的互斥任务
- 是否配置了 `scheduled_at`

### 8.3 OIDC 配置突然失效

优先检查：

- `system_config` 是否仍有数据
- PostgreSQL volume 是否被重建
- `CONFIG_ENCRYPTION_KEY` 是否变化
- OIDC Client Secret 是否仍可正确解密

### 8.4 任务执行失败但前端日志不完整

优先检查：

- Task detail 页面是否拿到了实时日志
- `backend` / `scheduler` 日志里是否有异常
- Worker 容器是否被提前退出

如果是 E2E 或真实 GitLab 集成问题，参见 [E2E_TESTS.md](E2E_TESTS.md)。

## 9. 升级与回滚建议

建议采用以下原则：

- 一次只发布一类改动，便于定位问题
- 保留上一版 `codify-backend:latest` 和 Worker 镜像标签
- 在升级前导出数据库
- 升级后优先验证：
  - `/health`
  - Dashboard 可访问
  - 手动创建任务
  - 一条真实或测试任务可执行

如果需要回滚：

1. 切回旧镜像标签
2. 重启 `backend`、`scheduler`、必要时 `nginx`
3. 如果问题与数据库迁移相关，再评估是否需要数据库级回滚

## 10. 生产环境操作红线

请避免以下高风险操作：

- 在生产环境跑带破坏性清理的 E2E 脚本
- 执行 `docker-compose down -v`
- 未备份就重置 PostgreSQL volume
- 未记录密钥就轮换 `SECRET_KEY` / `CONFIG_ENCRYPTION_KEY`
- 在未验证 Worker 镜像的情况下直接替换正式环境

### 10.1 导出 DB 绑定的 V2 Runtime Bundle（L3 证据）

只可从一个已验证的 V2 Task 或一个已知 bundle digest 导出；命令不读取当前 checkout、不会重新构建
Bundle，也不会通过 HTTP 获取内容。基础 Compose 将宿主机 `/opt/codify-archives` bind 到 backend
容器的同一路径，因此 `BUNDLE_EXPORT_DIR` 必须使用容器内的持久目录
`/opt/codify-archives/runtime-bundles`，不能写入容器层或使用控制机路径：

```bash
make worker-runtime-bundle-export TASK_ID=123 BUNDLE_EXPORT_DIR=/opt/codify-archives/runtime-bundles
```

导出结果固定为 `/opt/codify-archives/runtime-bundles/runtime-bundle-v2-<bundle-digest>/`，包含数据库中原始 tar 字节、规范化的
数据库 manifest 和各自 SHA-256 sidecar。目标已经存在、manifest/归档出现 secret 形态、或 Bundle 与
冻结的 V2 identity/evidence/platform 不一致时都会拒绝，不能覆盖或“清洗后继续”。一个 Bundle 仅证明
该 Task 选中的 Harness；四个 Harness 的 L3 证据必须来自四个分别验证通过的 Task。L3 是制品/绑定证据，
不是 Host 上的完整执行与 MR 验收（L4）。

## 11. 相关文档

- [文档索引](README.md)
- [项目总览 README](../README.md)
- [README.zh-CN.md](README.zh-CN.md)
- [GITLAB_OIDC_SETUP.md](GITLAB_OIDC_SETUP.md)
- [E2E_TESTS.md](E2E_TESTS.md)
