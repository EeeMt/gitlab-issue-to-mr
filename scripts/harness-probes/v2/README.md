# Open-Harness V2 probe 脚本目录

Phase 0 的 probe 生成/回放工具。raw 证据（脱敏后）落 `docs/harness-probes/v2/`；凭据与完整仓库内容不进入任何 fixture。

- [`replay_v2.py`](./replay_v2.py) — V1 canonical → V2 canonical 确定性回放（Claude/Codex），见 [docs/harness-probes/v2/claude/README.md](../../../docs/harness-probes/v2/claude/README.md)。

## Vi/OpenCode 探针说明

Pi RPC / OpenCode Server 的真实 probe 在远端目标架构（linux/amd64）容器内执行，raw 输出经脱敏后冻结到 `docs/harness-probes/v2/{pi,opencode}/`。probe 驱动逻辑（RPC 交互、SSE 订阅、abort）不随仓库分发以避免固化 host 环境细节；V2 集成阶段由 Bridge 测试直接覆盖同一边界。

- Pi 四场景（success/steer/followup/abort）raw：`docs/harness-probes/v2/pi/*.raw.jsonl`
- OpenCode 事件协议样本：`docs/harness-probes/v2/opencode/events.observed.jsonl`
