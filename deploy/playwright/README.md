# Codify Playwright Worker 使用手册

`codify-worker/playwright:1.62.0` 同时支持以下两种用途：

- 作为 Codify `mounted_kit` Worker Runtime，由 Agent 编写并执行无头 Playwright 测试。
- 作为独立的手工开发容器，使用 UI Mode、codegen、Inspector 和 headed 浏览器桌面调试。

两种用途共用一个镜像，但运行方式相互独立。Codify 执行任务时不会自动启动
UI Mode、Xvfb、VNC 或 noVNC；只有手工执行 `playwright-ui` 或
`playwright-desktop` 时才会启动交互服务。

## 1. 镜像内容和边界

镜像包含：

- Node.js 24
- `@playwright/test` 1.62.0
- TypeScript/前端工具链：typescript、ts-node、tsx、eslint + @typescript-eslint、
  prettier、@types/node
- Chromium、Firefox、WebKit 及其系统依赖
- 中文、Emoji 和常用西文字体
- Xvfb、Fluxbox、x11vnc、noVNC、websockify、xterm
- Git、SSH、curl、jq、Python 3、编译工具和常用诊断工具
- `playwright-ui`、`playwright-desktop`、`verify-playwright-runtime`

镜像不包含：

- Codify Worker Kit。Codify 运行时通过只读挂载提供。
- Claude CLI。需要由 Worker Profile 挂载，或在派生镜像中提供。
- 测试项目除镜像预装之外的任意 npm 依赖。
- Codify ENTRYPOINT。Codify 会使用 mounted Worker Kit 的 launcher 覆盖入口。

镜像内 Playwright 包和浏览器固定为 `1.62.0`；TypeScript/前端工具链版本同样固定并
锁进 lock 文件。测试项目不要安装其他版本的 Playwright，否则项目本地 `node_modules`
可能覆盖镜像版本，并找不到匹配的浏览器。

## 2. 构建镜像

### 2.1 普通构建

在仓库根目录执行：

```bash
docker build \
  --platform linux/amd64 \
  -f deploy/Dockerfile.playwright \
  -t codify-worker/playwright:1.62.0 \
  .
```

如果构建环境通过私有 npm Registry 下载依赖，可以通过 BuildKit secret 传入
`.npmrc`：

```bash
docker build \
  --platform linux/amd64 \
  --secret id=npmrc,src=/absolute/path/to/npmrc \
  -f deploy/Dockerfile.playwright \
  -t codify-worker/playwright:1.62.0 \
  .
```

构建阶段需要访问以下来源：

- `mcr.microsoft.com`：Playwright 基础镜像
- Ubuntu APT 仓库：字体、桌面和诊断工具
- npm Registry：固定版本的 `@playwright/test`

完全断网的目标环境不应重新执行 Dockerfile。应在联网构建机完成构建，再通过内网
Registry 或 Docker image archive 分发。

### 2.2 架构要求

镜像、Worker Kit、Claude CLI 和 Docker 主机必须使用兼容的 CPU 架构。例如：

```text
runtime image: linux/amd64
Worker Kit:    0.3.6-linux-amd64
Claude CLI:    linux/amd64
Docker host:   linux/amd64
```

如果同时存在 amd64 和 arm64 Worker，应分别构建和验证镜像，不要依赖透明模拟作为
生产执行方式。

## 3. 基础验证

### 3.1 检查工具和浏览器路径

```bash
docker run --rm \
  --user 1000:1000 \
  codify-worker/playwright:1.62.0 \
  verify-playwright-runtime --paths-only
```

### 3.2 启动三个无头浏览器

```bash
docker run --rm \
  --init \
  --ipc=host \
  --user 1000:1000 \
  codify-worker/playwright:1.62.0 \
  verify-playwright-runtime --launch
```

验证脚本会启动 Chromium、Firefox 和 WebKit，创建页面并执行一次 DOM 断言。

## 4. 作为 Codify Worker 使用

### 4.1 Worker Profile 前置条件

每台可能执行该 Profile 的 Docker 主机都必须准备：

- `codify-worker/playwright:1.62.0` 镜像
- 已安装且架构匹配的 Worker Kit，例如：
  `/opt/codify/worker-kits/0.3.6-linux-amd64`
- 可执行且架构匹配的 Claude CLI，例如：
  `/opt/codify/overrides/claude-2.1.200`
- 能够访问 GitLab、被测系统和内网模型服务的 Docker 网络

Worker Kit 路径和 Claude CLI 挂载路径都位于 Docker Engine 主机，而不是 Backend
容器或操作管理页面的电脑。

### 4.2 Worker Profile 示例

可在 Worker Profile 页面配置，或通过管理 API 创建等价配置：

```json
{
  "name": "Playwright 1.62",
  "description": "Headless UI automation runtime",
  "enabled": true,
  "image": "codify-worker/playwright:1.62.0",
  "runtime_mode": "mounted_kit",
  "worker_kit_version": "0.3.6",
  "worker_kit_path": "/opt/codify/worker-kits/0.3.6-linux-amd64",
  "codegraph_enabled": true,
  "volume_mounts": [
    {
      "host_path": "/opt/codify/overrides/claude-2.1.200",
      "container_path": "/usr/local/bin/claude",
      "mode": "ro"
    }
  ],
  "environment_variables": [
    {
      "key": "UI_TEST_ARTIFACT_DIR",
      "value": "/tmp/codify-runtime/artifacts/playwright",
      "is_secret": false
    },
    {
      "key": "PLAYWRIGHT_HTML_OPEN",
      "value": "never",
      "is_secret": false
    }
  ]
}
```

如果 Claude CLI 已通过其他路径提供，按实际情况调整只读挂载和
`CODIFY_CLAUDE_BIN`。不要把宿主机不存在的路径填入 Profile；远程 Docker 的 bind
mount 只会在 Docker 主机上解析。

### 4.3 验证已保存的 Worker Profile

在管理页面使用 Runtime Verification，smoke command 填写：

```bash
verify-playwright-runtime --launch
```

也可以调用管理 API：

```http
POST /api/worker-profiles/{profile_id}/verify-runtime
Content-Type: application/json

{"smoke_command":"verify-playwright-runtime --launch"}
```

该检查还会验证实际 Profile 的 Worker Kit、Claude CLI、挂载、环境和 UID 1000 执行
路径。修改镜像、Kit、Claude CLI、Docker 主机或 Profile 后都应重新执行。

### 4.4 保存截图、Trace、视频和 HTML 报告

Worker Kit 会提供以下任务级产物目录：

```text
CODIFY_ARTIFACT_DIR=/tmp/codify-runtime/artifacts
UI_TEST_ARTIFACT_DIR=/tmp/codify-runtime/artifacts/playwright
```

建议让 Playwright 在执行期间直接写入该目录。例如：

```ts
import path from 'node:path'
import { defineConfig } from '@playwright/test'

const artifactRoot =
  process.env.UI_TEST_ARTIFACT_DIR ?? path.resolve('test-results')

export default defineConfig({
  outputDir: path.join(artifactRoot, 'results'),
  reporter: [
    ['line'],
    ['html', { outputFolder: path.join(artifactRoot, 'html-report'), open: 'never' }],
  ],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
})
```

默认产物上限为总计 200 MiB、单文件 100 MiB、5,000 个条目。大量视频或长时间 Trace
可能超过限制，应按测试价值控制保留策略。

## 5. 手工使用 Playwright UI Mode

在测试项目目录执行：

```bash
docker run --rm -it \
  --init \
  --ipc=host \
  --user 1000:1000 \
  -p 127.0.0.1:9323:9323 \
  -v "$PWD:/workspace" \
  codify-worker/playwright:1.62.0 \
  playwright-ui
```

浏览器访问：

```text
http://127.0.0.1:9323
```

可以在命令末尾追加普通 Playwright 参数：

```bash
docker run --rm -it \
  --init \
  --ipc=host \
  --user 1000:1000 \
  -p 127.0.0.1:9323:9323 \
  -v "$PWD:/workspace" \
  codify-worker/playwright:1.62.0 \
  playwright-ui --project=chromium tests/login.spec.ts
```

环境变量：

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `PLAYWRIGHT_UI_HOST` | `0.0.0.0` | UI Mode 监听地址 |
| `PLAYWRIGHT_UI_PORT` | `9323` | UI Mode 容器端口 |

`EXPOSE 9323` 只是镜像元数据，不会自动发布端口，仍需显式使用 `-p`。

## 6. 手工使用桌面、codegen 和 Inspector

### 6.1 启动 noVNC 桌面

```bash
docker run --rm -it \
  --init \
  --ipc=host \
  --user 1000:1000 \
  -p 127.0.0.1:6080:6080 \
  -v "$PWD:/workspace" \
  codify-worker/playwright:1.62.0 \
  playwright-desktop
```

浏览器访问：

```text
http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=remote
```

桌面会打开一个 xterm，可执行：

```bash
playwright codegen https://target.example
playwright test --debug tests/login.spec.ts
playwright test --headed --project=chromium
```

### 6.2 直接启动 codegen

```bash
docker run --rm -it \
  --init \
  --ipc=host \
  --user 1000:1000 \
  -p 127.0.0.1:6080:6080 \
  -v "$PWD:/workspace" \
  codify-worker/playwright:1.62.0 \
  playwright-desktop \
  playwright codegen \
    -o tests/generated.spec.ts \
    https://target.example
```

先打开 noVNC 地址，再在 codegen 浏览器中操作。生成的文件会直接写入挂载的项目目录。

### 6.3 桌面环境变量

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `DISPLAY` | `:99` | Xvfb display，只接受 `:数字` |
| `PLAYWRIGHT_DESKTOP_GEOMETRY` | `1600x900x24` | 桌面分辨率和色深 |
| `PLAYWRIGHT_DESKTOP_HOST` | `0.0.0.0` | noVNC 监听地址 |
| `PLAYWRIGHT_DESKTOP_PORT` | `6080` | noVNC Web 端口 |
| `PLAYWRIGHT_VNC_PORT` | `5900` | 容器内部 VNC 端口 |
| `PLAYWRIGHT_VNC_PASSWORD_FILE` | 空 | 可选的 VNC 密码文件 |
| `PLAYWRIGHT_DESKTOP_LOG_DIR` | `/tmp/playwright-desktop-<uid>` | 桌面组件日志目录 |

`x11vnc` 只监听容器 loopback，由 websockify 转发；宿主机只需要发布 noVNC 的
`6080` 端口。

### 6.4 慢速网络下桌面卡顿 / "卡在连接中"

noVNC 要把整屏像素经 WebSocket 传到浏览器才显示桌面：连接时的那一帧和之后的
每次刷新，分辨率越高、色深越大，数据量越大。跨内网/跨 VPN 访问时觉得"卡在
连接中很久""操作不顺滑"，几乎都是**初始帧/刷新帧传得慢**，不是连接握手本身
的问题。按影响从大到小：

1. **降低分辨率**（效果最明显）。默认已是 `1600x900x24`；链路仍然偏慢时继续
   调小：

   ```bash
   -e PLAYWRIGHT_DESKTOP_GEOMETRY=1440x900x24 \
   ```

   必须 1080p 时显式覆盖回去：`-e PLAYWRIGHT_DESKTOP_GEOMETRY=1920x1080x24`。

2. **降到 16 位色深**（带宽再减半，适合很慢的链路；codegen 使用不受影响，只有
   VNC 画面颜色略失真）：

   ```bash
   -e PLAYWRIGHT_DESKTOP_GEOMETRY=1440x900x16 \
   ```

3. **连接长时间卡住时，去掉 `resize=remote`**。`resize=remote` 会在连接时（以及
   每次改变浏览器窗口大小后）触发 Xvfb RANDR 缩放并**重发整屏**，慢链路上这一
   步可能卡很久。改用客户端缩放：

   ```text
   http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale
   ```

4. **降低 noVNC 质量/提高压缩**。访问 URL 追加参数，`quality` 越低画质越差但
   越快，`compression` 越高数据越少但两端 CPU 越高：

   ```text
   http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=remote&quality=3&compression=4
   ```

5. `x11vnc` 的 `-wireframe` / `-scrollcopyrect` / `-wirecopyrect` 默认已开启，
   会用 CopyRect 代替重传像素，**不要**额外加 `-ncache`（noVNC 无法渲染其缓存
   区域，反而更卡）。

6. 尽量走 SSH 隧道访问（见第 7 节），隧道内置压缩。

## 7. 远程 Docker 主机

使用远程 Docker context 时有两个重要边界：

1. `-v "$PWD:/workspace"` 中的宿主机路径在 Docker daemon 主机上解析，不是当前
   客户端电脑上的路径。
2. `-p 127.0.0.1:6080:6080` 绑定的是远程 Docker 主机的 loopback。

推荐先在远程主机准备项目目录，再通过 SSH 隧道访问交互端口：

```bash
ssh \
  -L 6080:127.0.0.1:6080 \
  -L 9323:127.0.0.1:9323 \
  user@worker-host
```

不要为了方便将 noVNC 或 UI Mode 直接发布到整个内网。

## 8. noVNC 安全

noVNC 默认没有密码。最安全的简单用法是始终绑定宿主机 loopback：

```text
-p 127.0.0.1:6080:6080
```

如果必须增加 VNC 密码，先创建密码文件：

```bash
mkdir -p .playwright-secrets

docker run --rm -it \
  --user 1000:1000 \
  -v "$PWD/.playwright-secrets:/secrets" \
  codify-worker/playwright:1.62.0 \
  x11vnc -storepasswd /secrets/vnc.pass
```

启动桌面时只读挂载密码文件：

```bash
docker run --rm -it \
  --init \
  --ipc=host \
  --user 1000:1000 \
  -p 127.0.0.1:6080:6080 \
  -v "$PWD:/workspace" \
  -v "$PWD/.playwright-secrets/vnc.pass:/run/secrets/vnc.pass:ro" \
  -e PLAYWRIGHT_VNC_PASSWORD_FILE=/run/secrets/vnc.pass \
  codify-worker/playwright:1.62.0 \
  playwright-desktop
```

仍然建议保留 loopback 绑定。VNC 密码不能替代网络隔离、SSH 和访问审计。

## 9. 离线分发

### 9.1 单独导出镜像

在已有镜像的联网构建机执行：

```bash
docker save codify-worker/playwright:1.62.0 \
  | gzip -1 \
  > codify-worker-playwright-1.62.0.tar.gz
```

复制到每台离线 Docker 主机后加载：

```bash
gunzip -c codify-worker-playwright-1.62.0.tar.gz | docker load
```

加载后执行基础验证，确认传输、架构和浏览器启动均正常。

### 9.2 纳入 Codify offline bundle

`make offline-bundle-export` 不会自动构建本镜像。应先完成 Playwright 镜像构建，然后：

```bash
cp \
  deploy/offline-bundle/config/worker-images.txt.example \
  deploy/offline-bundle/config/worker-images.txt
```

在 `deploy/offline-bundle/config/worker-images.txt` 中加入一行：

```text
codify-worker/playwright:1.62.0
```

再执行：

```bash
make offline-bundle-export
```

生成的 `deploy/offline-bundle/images/codify-offline-images.tar.gz` 会包含该 runtime
镜像。每台能够执行此 Worker Profile 的 Docker 主机都必须加载镜像并安装对应 Worker
Kit；只在 Codify 应用主机加载是不够的。

## 10. 项目依赖和目录权限

镜像保证提供 Playwright 1.62.0 和一套固定版本的 TypeScript/前端工具链
（typescript、ts-node、tsx、eslint + @typescript-eslint、prettier、@types/node），
可直接执行 `tsc`、`ts-node`、`tsx`、`eslint`、`prettier`。项目如果还依赖
Axios、dotenv、数据库客户端或其他 npm 包，需要满足以下任一条件：

- 项目依赖已存在于适用于 Linux 的 `node_modules`。
- 容器能访问内网 npm Registry 并执行 `npm ci`。
- 通过派生镜像预装项目依赖。
- 使用已准备好的 Docker volume 保存 Linux 依赖。

预装工具链是兜底基线，不是硬锁定：Node 就近解析优先，项目本地 `node_modules` 会
覆盖镜像版本。需要其他工具版本时，直接在项目里安装即可；但要避免让本地
`@playwright/test` 与镜像 1.62.0 不一致。

不要直接复用 macOS 或 Windows 生成的含原生模块 `node_modules`。

手工模式推荐使用 UID/GID `1000:1000`。挂载项目必须允许 UID 1000 写入，否则
codegen、快照更新和测试报告可能出现 `EACCES`。不要通过长期使用 root 来掩盖宿主机
权限问题。

## 11. 内网 HTTPS 和自定义 CA

Codify 的 `CUSTOM_CA_BUNDLE` 会配置 Git、Node.js 和 Python 的 CA 环境，但不保证三个
浏览器都自动信任内网自签 CA。应使用真实内网 HTTPS 地址分别验证 Chromium、Firefox
和 WebKit。

推荐将组织根证书安装进受控的派生 runtime 镜像。仅在明确接受测试安全风险时，才在
项目 Playwright 配置中设置：

```ts
use: {
  ignoreHTTPSErrors: true,
}
```

## 12. 常见问题

### UI Mode 无法访问

- 确认命令使用 `-p 127.0.0.1:9323:9323`。
- 确认容器日志中没有测试配置加载错误。
- 远程 Docker 必须使用 SSH 隧道，端口不在客户端本机。
- 检查宿主机端口是否已被其他容器占用。

### noVNC 页面空白或无法连接

- 查看 `/tmp/playwright-desktop-<uid>/` 下的 `xvfb.log`、`fluxbox.log`、
  `x11vnc.log` 和 `websockify.log`。
- 确认发布的是 Web 端口 `6080`，不是内部 VNC 端口 `5900`。
- 确认自定义 `PLAYWRIGHT_VNC_PASSWORD_FILE` 可读且挂载为普通文件。

### `playwright` 找不到浏览器

- 执行 `playwright --version`，必须为 `1.62.0`。
- 检查项目是否安装了其他版本的 `@playwright/test`。
- 不要覆盖镜像中的 `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`。

### codegen 不能写入测试文件

- 检查挂载项目对 UID 1000 是否可写。
- 确认远程 Docker 使用的是远端真实项目路径。
- 确认输出路径位于 `/workspace` 下，而不是容器临时目录。

### Chromium 内存不足或异常退出

手工运行优先使用 `--ipc=host`。在共享宿主机上不希望共享 IPC namespace 时，可尝试
改用较大的 `--shm-size`，并重新执行三浏览器 smoke：

```text
--shm-size=2g
```

### Codify 验证通过但任务仍失败

- 确认真实任务使用了预期 Worker Profile snapshot。
- 确认目标 Docker 主机已加载相同 image ID。
- 确认 Worker Kit 和 Claude CLI 安装在实际 Docker 主机，而不是 Backend 主机。
- 检查 Worker 网络是否能解析 GitLab、被测系统和内网模型服务。
- 用实际 Profile 再次运行 `verify-playwright-runtime --launch`。
