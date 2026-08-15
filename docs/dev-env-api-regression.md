# 开发环境 API 回归验证手册

> 用于对开发环境（本地 `make up` 启动的 docker-compose，页面入口 http://<host>:8880）做 Multi-Harness / Phase 1+ 的 L4 回归验证。本文档持续完善，新增端点或验证步骤时请同步更新。

## 1. 环境与前提

- 开发环境由 `make up` 启动（backend / scheduler / nginx / postgres 四个服务，代码烘焙进镜像，postgres 数据在 named volume `postgres_data` 中持久化）。
- **部署拓扑**：本机是开发机，Docker 通过 remote context 连到目标主机（`docker context show` 应为 `remote` → `ssh://root@<host>`）。`make up` 的构建与容器都发生在目标主机上。
- 目标主机 8880 端口是 nginx 前端入口；`/api/*` 由 nginx 反代到 backend。
- 认证：API 全部要求 session cookie（OIDC 或本地账号）。未登录访问 `/api/tasks/...` 返回 `401`。
- 环境状态探测（无需认证）：

```bash
curl -s http://<host>:8880/api/auth/bootstrap-status
# {"initialized":true,"oidc_configured":true,"total_users":3}
```

## 2. 登录与保存 session

本地账号登录（用户必须已在系统里存在且有 `local_password_hash`）：

```bash
curl -s -c /tmp/codify_cookies.txt \
  -X POST http://<host>:8880/api/auth/local/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<user>","password":"<pass>"}'
```

之后所有请求带上 `-b /tmp/codify_cookies.txt`。cookie 名为 `codify_session`，TTL 默认 5 天。

**注意：**
- 不要把真实口令写进仓库或文档；用完后删除 cookie 文件：`rm -f /tmp/codify_cookies.txt`。
- 管理员接口（如 GitLab 连通性测试）需要 `platform_admin` 角色。

## 3. 常用只读端点

| 端点 | 说明 |
|---|---|
| `GET /api/tasks/{id}` | 任务详情：status、error_message、commit_sha、deltas、usage、worker_profile/kit、issue/MR 引用 |
| `GET /api/tasks/{id}/logs` | 任务日志列表（system_init / tool_call / diagnostic ...） |
| `GET /api/tasks/{id}/archive` | runtime archive 元信息（archive_name、size、created_at、file_exists） |
| `GET /api/tasks/{id}/archive/download` | 下载 `task-<id>-runtime-archive.tar.gz` |
| `GET /api/tasks/{id}/workspace` | 工作区信息（持久工作区） |
| `GET /api/tasks/{id}/payloads/{payload_id}` | 工具调用输入/输出 payload |
| `POST /api/config/gitlab/test` | 用当前或待保存配置测 GitLab 连通性（`/version` + `/user`），返回 200 即 bot token 有效 |

```bash
# 任务详情（重点字段）
curl -s -b /tmp/codify_cookies.txt http://<host>:8880/api/tasks/463 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ['id','status','task_mode','session_mode','commit_sha','additions','deletions','total_changes','error_message','worker_kit_version','input_tokens','output_tokens']}); print('mr:', d['issue']['merge_request_url'])"

# 下载 archive 并列出内容
curl -s -b /tmp/codify_cookies.txt -o /tmp/task-463.tar.gz http://<host>:8880/api/tasks/463/archive/download
tar tzvf /tmp/task-463.tar.gz

# GitLab 连通性（bot token 是否有效）
curl -s -b /tmp/codify_cookies.txt -X POST http://<host>:8880/api/config/gitlab/test \
  -H 'Content-Type: application/json' -d '{"integration":{}}'
# 期望：{"server_version":"18.5.5-ee","username":"ai-bot","gitlab_url":"http://...:8080"}
```

## 4. 新建任务（追加到已有 Issue）

```bash
curl -s -b /tmp/codify_cookies.txt -X POST http://<host>:8880/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"issue_id":83,"user_prompt":"Create a hello world in python.","priority":1,"provider_id":6,"require_changes":true,"task_mode":"execute","session_mode":"fresh"}'
```

要点：
- `issue_id` 必填；`user_prompt` 缺省用 issue.description。
- `worker_profile_id` **不可传**（由 Issue 固定，传了会被 422 拒绝）。
- `task_mode`：`execute`（实施+提交）或 `plan`（只出方案不写文件）。
- `session_mode`：`continue`（续跑上一会话，需要上一任务存了**真实** session_id）或 `fresh`。
- 创建事务内会冻结 `TaskWorkerProfileSnapshot` 并绑定不可变 Runtime Bundle（`runtime_bundle_id`），创建即生效。
- 轮询终态时直接定时查 `GET /api/tasks/{id}`，短任务（几十秒）不必用同步监听脚本。

## 5. L4 验证步骤（Phase 1 退出门禁相关）

1. **任务完成**：`GET /api/tasks/{id}` 的 `status=completed`，`commit_sha` 非空（execute 模式），`additions/deletions` 与改动一致，`error_message=null`。
2. **MR 引用**：`issue.merge_request_url` 存在；worker 会更新已有 MR 描述或新建 MR。
3. **Canonical 协议**：下载 archive，校验 `event.jsonl`：

```bash
tar xzf /tmp/task-463.tar.gz event.jsonl harness-result.json
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

4. **harness-result**：`harness-result.json` 的 `harness_key`、`adapter_version`、`cli_version`、`session_id` 齐全；`session_id` 应为**真实 UUID**（不是 `<UUID:...>` 占位符）——这是 resume 可用性的关键（见已知问题）。
5. **真实 Git/MR**：任务 `delivery.completed` / `worker.finalization` 事件携带 `commit_sha`；MR 可在 GitLab Web 上核对。

## 6. 已知问题与回归点

- **resume 被 session_id 脱敏破坏（已修复并验证）**：`claude_events.py` 现在在 sanitize 前捕获真实 session_id，并让 canonical 事件的 `session_id` 字段携带真实值（后端从事件投影 `output_session_id`）；raw 流与其它 UUID 仍脱敏。**验证证据（2026-08-03）**：Task 465（fresh plan）产出真实 session `2278bf1c-...`；Task 466（continue）CLI 参数为 `--resume 2278bf1c-...`（真实 UUID，不再是 `<UUID:...>`），续跑同一会话并 completed，`output_session_id` 仍为 `2278bf1c-...`。回归点：`continue` 任务不应再报 `Provided value "<UUID:..." is not a UUID`。
- **cancel 语义（已修复并验证）**：`bootstrap.sh` 增加 TERM/INT trap（置 `CODIFY_CANCELLED=1` 并以 143 退出），`common.sh` finalizer 在取消时产出 `harness.failed(cancelled)` + `run.failed(cancelled)`；`runner.sh` 把 adapter 改为后台运行 + `wait`，否则 bash 在前台子进程上延迟执行 TERM trap，`docker stop` 10s 后升级 SIGKILL 导致 finalizer 无法产出终态。**验证（Task 469）**：RUNNING 时 cancel → canonical `harness.failed(cancelled)` → `worker.finalization` → `run.failed(cancelled)`，任务 `cancelled`，容器清理。DB 与 replay 一致。
- **极早取消竞态（已修）**：`task_action_routes.py` 的 cancel handler 之前会 `container.remove()`，在 scheduler 摄取/归档前删掉容器，导致**极早取消**（`run.started` 未发出前）的 runtime archive 丢失。修复：cancel handler 不再移除容器，移除与 issue 锁释放交给 scheduler 的 worker finalization（它在排空日志流、摄取 canonical 终态之后才做）。**验证**：Task 476（run.started 已发出后取消）→ canonical `harness.failed(cancelled)` → `run.failed(cancelled)` 正常摄取；Task 475（run.started 前取消）→ archive 保留（console.log + repository-preparation），无 canonical 终态属设计行为（attempt 从未初始化）。
- **timeout L4（已测）**：`task_timeout` 是全局设置，默认 3700s。测试方法：`PATCH /api/config/runtime` 设 `task_timeout=60`（API 下限 60s）→ 创建较重任务 → 60s 后 backend 记 `Task timed out after 60s`，canonical 产出 `harness.failed(timeout)` → `worker.finalization` → `run.failed(timeout)`，任务 `failed`，DB 与 replay 一致 → 测完恢复 `task_timeout=3700`。**验证（Task 470）** 通过。
- **retry（已验证）**：Task 470（timeout 失败）→ 471（retry）completed + commit `3ea0b283`。471 的 bundle digest 与 470 相同（`828343df...`），证明 retry 原样复制源任务冻结的 bundle，即使新版 bundle 已可用也不换。
- **token 部分脱敏泄漏**：`GITLAB_TOKEN` 尾部含 `_`/`.` 的片段未完全脱敏，可能出现在 `error_message`。验证时注意错误信息里不应残留 `glpat-` 片段。
- **发版硬边界**：迁移前历史 Task 无 Runtime Bundle，只能只读/关闭，不允许 retry 或执行；重试复制原 Task 的 Harness/Adapter/Endpoint/Bundle。

## 7. 回归后清理

```bash
rm -f /tmp/codify_cookies.txt /tmp/task-*.tar.gz /tmp/event.jsonl /tmp/harness-result.json
```

## 8. 调试经验补充（2026-08-04）

### 改动 worker 脚本后如何让 dev 环境生效

worker 容器执行的 entrypoint 来自 Task Runtime Bundle——backend 在任务创建时从镜像内
`/opt/codify/runtime-source` 生成（`Dockerfile.backend` 把 `deploy/` 烘焙进镜像，`CODIFY_RUNTIME_SOURCE_DIR` 指向它）。
所以改动 `deploy/worker-entrypoint/**` 或 `deploy/ci-claude.sh` 后**必须重建镜像**：

```bash
make rebuild-backend                                  # 重建 + 重启 backend
cd deploy && docker-compose --env-file .env.test up -d scheduler   # scheduler 同镜像，须显式 recreate 才吃到新层
docker exec codify-backend grep -c "<特征串>" /opt/codify/runtime-source/deploy/worker-entrypoint/<file>  # 确认已烘焙
```

注意：retry 任务复用原任务冻结的 bundle（bundle digest 不变），要验证新改动必须**新建**任务。

### 远程 docker context 的坑

`docker context show` 为 `remote`（ssh://root@host）。`docker run -v <本地路径>:/x` 挂的是**目标主机**路径，
本地仓库不能直接挂进容器。想拿容器内脚本到本地/测试容器：

```bash
docker run --rm --entrypoint cat <image> /opt/codify/runtime-source/deploy/.../file.sh > /tmp/x.sh
```

别直接 `docker run <image> cat <path>`——backend 镜像有 entrypoint banner，会混进 stdout（用 `--entrypoint cat` 绕开）。

### 验证 harness 运行用户（probe 模板）

让任务 prompt 执行 `id -u` 并把结果写入仓库文件（如 uid-probe.txt），提交后三重确认运行用户：
- workspace 上该文件**内容 + 属主**（codify 应写 1000:1000）
- archive 里 `harness-events/<harness>.jsonl` 的 `aggregated_output`（`id -u` → `1000`）
- 任务 RUNNING 时现场 `docker exec <worker> ps -eo pid,user,uid,args | grep -E "[c]odex exec"`

顺带 `find /workspace/.git -user root` 查旧 run 遗留的 root-owned 对象（条件 chown 只在这些存在时才归一化）。

### `session_mode=continue` 的 harness 约束

continue 必须沿用 issue 当前 lineage 的 harness；传不匹配的 `harness_key` 返回 422
「续跑会话必须沿用原 Harness；切换 Harness 请勾选"使用新会话执行"」。issue 混用过 claude/codex
时 continue 会被拒，改用 lineage 干净的 issue 或 `session_mode=fresh`。
