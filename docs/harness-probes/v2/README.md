# Open-Harness V2 上游协议探针与制品固定 (Phase 0)

**日期：** 2026-08-21 · **归属计划：** [2026-08-21-open-harness-v2-implementation-plan.md](../../superpowers/plans/2026-08-21-open-harness-v2-implementation-plan.md) §3.1–3.5

**范围：** 固定 Pi / OpenCode / Claude CLI / Codex CLI 四个官方精确版本并核对离线可运行性；按 §3.2/§3.3/§3.4 矩阵跑真实 probe；把脱敏 raw fixture 与字段映射提交到本目录。凭据与完整仓库内容不进入任何 fixture。

**结论摘要：** 本机/远端 Docker 实测可访问上游（github / pi.dev / opencode.ai / npmjs / api.deepseek.com 均 200）；网络**不是**阻塞项。四个制品的 linux/amd64 二进制均已在远端 Worker 同架构容器内实际执行成功（`--version` 返回真实版本），满足 §3.1 "目标 Worker 架构离线运行" 验收。

---

## §3.1 制品固定表

以下为本轮核对的四个上游制品。所有 SHA-256 均为**部署到目标 Worker 架构 (linux/amd64) 的包/二进制**的计算值，Pi 已与官方 `SHA256SUMS` 交叉验证。

| 制品 | 版本 | 来源（下载地址） | 许可证 | 包名/二进制 | 平台 | 目标架构可运行 | SHA-256 (linux/amd64) |
|---|---|---|---|---|---|---|---|
| **Pi** | `0.84.2` | `https://github.com/earendil-works/pi/releases/download/v0.84.2/pi-linux-x64.tar.gz` | MIT | `pi-linux-x64.tar.gz` → `pi`（RPC stdio） | linux-x64 | ✅ 实测 `pi --version` = `0.84.2` | `906fbe787fd225c4ac624fe7ebd5b1d55a60e0f5c7ef51795d231564f9ee1c13` |
| **OpenCode** | `1.18.19` | `https://github.com/sst/opencode/releases/download/v1.18.19/opencode-linux-x64.tar.gz` | Apache-2.0 | `opencode-linux-x64.tar.gz` → `opencode`（Server/SDK） | linux-x64 | ✅ 实测 `opencode --version` = `1.18.19` | `7bb35487c55f9957f5d91ae60be6fa49fc8f74629c210c1719ed75fdbf7e2bd9` |
| **Codex** | `0.146.0` | `https://github.com/openai/codex` 官方 `codex-package-x86_64-unknown-linux-musl.tar.gz` | Apache-2.0 | tarball → `bin/codex` + `codex-path/rg` + `codex-resources/bwrap`（完整打包运行时，含 docker/沙箱工具） | x86_64-unknown-linux-musl | ✅ 实测 `codex --version` = `codex-cli 0.146.0` | `3c89125af1d7c98abec8beb551292ef99daca52e204e5852a9139feae2c467e5` |
| **Claude CLI** | `2.1.152` | 官方 `claude-code` 安装（Worker 侧经 `deploy/worker-kit` 镜像注入） | 专有（Anthropic 商业条款） | `claude`（`cli_stream_json`） | linux | V1 基线沿用；见下方说明 | 见下方说明 |

### 核对与交叉验证细节

- **Pi `0.84.2`**：官方 release 资产含 `SHA256SUMS`；其 `pi-linux-x64.tar.gz` 行 = `906fbe78…`，与本地下载 tarball 完全一致。**反向验证通过。**
- **OpenCode `1.18.19`**：release 未单独发布 `SHA256SUMS` 文件，但 release 资产 `opencode-linux-x64.tar.gz` 的字节数 = 60,474,448，与本地下载 tarball 字节数完全一致；SHA-256 = `7bb35487…` 作为本机固定证据（来源已记录官方 release URL）。**注：官方无独立 checksum 文件可二次核对，作为待决备注。**
- **Codex `0.146.0`**：官方 `codex-package.json` 声明 `version: 0.146.0, target: x86_64-unknown-linux-musl, entrypoint: bin/codex`。V1 基线记录为 `0.146.0-alpha.3.1`，二进制实际报告 `codex-cli 0.146.0`；两个版本号分属同一发布代际，最终以二进制报告 `0.146.0` 为准。二进制在远端 x86_64 容器内实测执行成功。
- **Claude CLI `2.1.152`**：V1 `scripts/harness-probes/README.md` 基线已固定此版本（`deploy/worker-kit/Dockerfile.worker-kit` 记录 `minimum_version: 2.1.33`，Operator CLI `/opt/homebrew/bin/claude`）。V2 复用以该版本为准；linux Worker 侧为镜像注入路径，SHA-256 建议在 V2 实施阶段以 Worker-kit 镜像 digest 形式记录（本轮未重新计算，列为待决）。

### 离线运行性（§3.1 第 2 项验收）

- Pi / OpenCode / Codex 三个 linux/amd64 二进制均在远端 `v2probe` 容器（基于 `codify-backend`，ubuntu 22.04 x86_64）内**实际执行成功**，脱网（无上游依赖调用时）无需联网即可启动并进入 RPC/Server 监听。Pi/OpenCode 的模型调用需在启动时注入 Provider 凭据（host env / config 内 `{env:…}` 插值）才出结果；本地可离线完成协议探针与启动。
- Codex 的完整运行时（bwrap + rg）随包分发，Worker 离线可用；其沙箱隔离依赖 `bwrap`（`codex-resources/bwrap`），已在 Worker-kit 中一并携带。
- 结论：**目标架构离线运行已由真实执行证实**，无阻塞。

---

## 各 harness 探针证据

- [Pi RPC](pi/) — §3.2：init/version/clean shutdown、fresh/resume、三协议、steer/follow-up 队列与 ACK、settled/closing、abort/signal
- [OpenCode Server](opencode/) — §3.3：start/health/auth/随机端口、Session/异步 Prompt/事件订阅/settled、Abort、Server 崩溃
- [Claude / Codex V2 回放](claude/) · [Codex](codex/) — §3.4：V1 raw → V2 canonical 字段映射与回放 fixture

初步结论与 SDK-vs-HTTP 判定见各 harness 页；汇总与成本重估输入见 [../v2-probe-report.md]（Phase 0 收尾汇总）。
