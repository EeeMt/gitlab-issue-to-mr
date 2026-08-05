# Multi-Harness 直接切换与生产验收证据模板

> 配套 Runbook：[multi-harness-rollout.md](multi-harness-rollout.md)

本模板用于逐 Host / 逐 Harness 收集可复制的 Phase 3 证据。真实 Host 名称、内部地址、token、私有仓库
URL 和敏感日志不得写入 Git；本文件只保留脱敏占位符。真实证据保存在受控发布系统，每份证据注明来源
任务/命令、时间、执行人和审批人。

## 1. 发布冻结清单

| 冻结项 | 值 | archive/digest | manifest/digest | 审批人 |
|---|---|---|---|---|
| Backend image | `<backend-image>` | `<repo@sha256:...>` | content `<sha256:...>` | `<approver>` |
| Frontend/Nginx image | `<nginx-image>` | `<repo@sha256:...>` | content `<sha256:...>` | `<approver>` |
| Migration head | `<revision>` | - | - | `<approver>` |
| Worker Kit amd64 | `<version>` | `<sha256>` | `<sha256>` | `<approver>` |
| Worker Kit arm64 | `<version>` / not required | `<sha256>` / N/A | `<sha256>` / N/A | `<approver>` |
| Runtime image | `<runtime-image>` | `<repo@sha256:...>` | content `<sha256:...>` | `<approver>` |
| Claude CLI | `<version>` | `<sha256>` | source/path | `<approver>` |
| Codex CLI | `<version>` | `<sha256>` | source/path | `<approver>` |
| Runtime Bundle | `<digest>` | Adapter claude/codex version + digest | contract/event schema | `<approver>` |
| Profile payload | `<profile-id/name>` | kit/image/digest/harnesses/constraints | sandbox/approval/credential mode | `<approver>` |
| 回滚坐标 | 旧 Profile/Kit/image | `<digest>` / `<path>` | 可用性确认 | `<approver>` |

## 2. Host 部署矩阵

| Host alias | Arch | Docker version | 连接方式 | Kit root | Runtime images | CA | 网络出口 | 旧 Profile | 目标 Profile | 回滚负责人 |
|---|---|---|---|---|---|---|---|---|---|---|
| `<host-a>` | `<arch>` | `<version>` | `<daemon/ssh>` | `<path>` | `<image list>` | `<path>` | `<egress>` | `<id>` | `<id>` | `<owner>` |

## 3. 逐 Host / 逐 Harness verify-runtime

| Host | Harness | 时间 | Kit manifest digest | Runtime Bundle/Adapter digest | Image digest | CLI source/path/version/binary digest | verify task ID / exit code | 脱敏日志摘要 | 审批人 |
|---|---|---|---|---|---|---|---|---|---|
| `<host-a>` | claude | `<ts>` | `<sha256>` | `<digest>` | `<repo@sha256>` | `<path>/<version>/<sha256>` | `<id>` / `0` | `<summary>` | `<approver>` |
| `<host-a>` | codex | `<ts>` | `<sha256>` | `<digest>` | `<repo@sha256>` | `<path>/<version>/<sha256>` | `<id>` / `0` | `<summary>` | `<approver>` |

## 4. 真实验收矩阵

| 用例 | Harness | Task ID | Attempt ID | Host | Profile snapshot | MR/commit | archive digest | 结果 | 人工结论 |
|---|---|---|---|---|---|---|---|---|---|
| 新 Issue 首个 execute + Git/MR | claude/codex | `<id>` | `<id>` | `<host>` | `<profile snapshot>` | `!<iid>` / `<sha>` | `<sha256>` | passed | `<owner>` |
| 无变更 / require_changes | ... | | | | | | | | |
| resume 同一 namespace | ... | | | | | | | | |
| fresh 不恢复旧 session | ... | | | | | | | | |
| namespace 变更新 lineage | ... | | | | | | | | |
| Claude → Codex → Claude session 隔离 | ... | | | | | | | | |
| retry 冻结复用 | ... | | | | | | | | |
| Skills 不污染 workspace | ... | | | | | | | | |
| 工具失败/认证/限流/网络/protocol 分类 | ... | | | | | | | | |
| cancel / timeout / SIGTERM/KILL 清理 | ... | | | | | | | | |
| archive 清洗与离线回放 | ... | | | | | | | | |
| Git/MR summary/Mermaid/CodeGraph | ... | | | | | | | | |

## 5. 切换记录

| 时间 | 操作 | Profile/Host | 切换前 | 切换后 | 证据 |
|---|---|---|---|---|---|
| `<ts>` | 直接切换 | `<profile>` | image tag / kit `<v>` | `repo@sha256` / kit `<v>` | verify task + smoke task |
| `<ts>` | 切换后 smoke | claude | - | `run.completed` | `<task ids>`, MR `!<iid>` |
| `<ts>` | 切换后 smoke | codex | - | `run.completed` | `<task ids>`, MR `!<iid>` |

## 6. 指标与观察

| 指标 | 切换前基线 | 切换后观察值 | 阈值 | 是否批准 |
|---|---|---|---|---|
| 成功率 | `<%>` | `<%>` | `>= 基线` | yes/no |
| P95 耗时 | `<s>` | `<s>` | `<= 基线 × 1.5` | yes/no |
| cancel 完成率 | `<%>` | `<%>` | 记录 | yes/no |
| timeout | `<n>` | `<n>` | 记录 | yes/no |
| protocol error | `<n>` | `<n>` | `<= 基线 × 1.5` | yes/no |
| worker cleanup error | `<n>` | `<n>` | 记录 | yes/no |

## 7. 回滚演练

| 场景 | 时间 | 操作 | 结果 | 证据 |
|---|---|---|---|---|
| 新 Kit 验证失败 | `<ts>` | Host 标记不可路由 | passed | `<verify id>` |
| Codex Provider 不可达 | `<ts>` | 路由排除/告警 | passed | `<task id>` |
| 单 Host 故障 | `<ts>` | 切换至备用 Host | passed | `<task id>` |
| canonical protocol error 上升 | `<ts>` | 停新任务 | passed | `<analytics>` |
| Profile/Kit 回滚 | `<ts>` | 恢复旧 image/Kit + re-verify | passed | `<verify id>` |
| replacement Issue + Claude smoke | `<ts>` | 旧稳定 Profile 新建 Issue/Task | passed | `<task id>` |

## 8. 签署

| 检查项 | 证据位置 | 通过 | 签署人 |
|---|---|---|---|
| Host/Profile 矩阵完整 | `<link>` | yes/no | `<approver>` |
| 制品冻结与校验完整 | `<link>` | yes/no | `<approver>` |
| 逐 Host verify-runtime 通过 | `<link>` | yes/no | `<approver>` |
| 真实验收矩阵无 P0/P1 | `<link>` | yes/no | `<approver>` |
| 直接切换与稳定观察完成 | `<link>` | yes/no | `<approver>` |
| 回滚演练通过 | `<link>` | yes/no | `<approver>` |
| Runbook/告警/责任人交接 | `<link>` | yes/no | `<approver>` |
