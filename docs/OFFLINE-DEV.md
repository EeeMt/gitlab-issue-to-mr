# Codify 内网离线迁移实施方案

本文档详述如何将 Codify 项目从有互联网的环境，完整迁移到**无互联网**的内网环境进行**开发 + 构建 + 测试 + 部署**。

> **适用场景**：目标环境无法访问 PyPI、npmjs、Docker Hub、GitHub、claude.ai 等任何公网资源。

---

## 目录

- [1. 总览](#1-总览)
- [2. 依赖清单](#2-依赖清单)
- [3. 在线环境打包（Phase A）](#3-在线环境打包phase-a)
- [4. 内网环境部署（Phase B）](#4-内网环境部署phase-b)
- [5. 内网开发环境搭建（Phase C）](#5-内网开发环境搭建phase-c)
- [6. 内网 Docker 镜像重新构建（Phase D）](#6-内网-docker-镜像重新构建phase-d)
- [7. 特殊组件处理](#7-特殊组件处理)
- [8. 验证清单](#8-验证清单)
- [9. 日常维护与更新流程](#9-日常维护与更新流程)
- [10. 故障排查](#10-故障排查)

---

## 1. 总览

### 1.1 迁移分层

| 层 | 用途 | 包含内容 | 大小估算 |
|----|------|----------|----------|
| **L1 — Docker 镜像** | 部署运行 | 4 运行镜像 + 6 基础镜像 | ~3.5 GB |
| **L2 — Python 依赖** | 后端开发/测试/构建 | pip wheels (prod + test + e2e) | ~300 MB |
| **L3 — Node.js 依赖** | 前端开发/构建 | node_modules + npm cache | ~500 MB |
| **L4 — 特殊二进制** | Worker 容器 + E2E | Claude CLI + Playwright Chromium | ~400 MB |
| **L5 — 源码** | 全部 | Git 仓库 | ~50 MB |

**总计打包大小：约 4.5–5 GB**

### 1.2 内网必备基础设施

开始迁移前，确认内网环境具备以下条件：

| 组件 | 要求 | 备注 |
|------|------|------|
| Docker Engine | 24.0+ | 需能运行 `docker load` / `docker compose` |
| Docker Compose | v2.x | plugin 模式或独立二进制 |
| Python | 3.11+ | 用于本地后端开发 |
| Node.js | 18+ (推荐 22.x) | 用于本地前端开发 |
| Git | 2.x | 用于版本控制 |
| GitLab | 内网实例 | Codify 的 MR/issue 操作目标 |
| LLM API | Claude 兼容端点 | 内网 Claude API 代理或兼容服务 |
| 存储 | ≥20 GB 可用空间 | 镜像 + 数据库 + 工作目录 |

### 1.3 架构差异

内网部署与公网部署唯一的架构差异：

```
公网: Dockerfile → curl/pip/npm 从公网下载 → 构建镜像
内网: 预打包 bundle → docker load / pip --find-links / npm --offline → 直接使用
```

---

## 2. 依赖清单

### 2.1 Docker 基础镜像

**运行镜像**（直接部署用）：
```
codify-backend:latest      后端 API + 调度器（共用同一镜像）
codify-nginx:latest        前端静态资源 + 反向代理
codify-worker:latest       AI 工作容器（Claude CLI + Git + Java + Maven）
postgres:16-alpine         PostgreSQL 数据库
```

**构建基础镜像**（如果需要在内网重新 `docker build`）：
```
ubuntu:22.04               backend 构建/运行基础
node:22-alpine             frontend 构建阶段
nginx:alpine               frontend 运行阶段
debian:bookworm-slim       worker claude-installer 阶段
python:3.11-slim           worker 运行阶段 + E2E 测试镜像
```

### 2.2 Python 依赖

**生产** (`backend/requirements.txt`)：
```
fastapi>=0.109.0            uvicorn[standard]>=0.27.0
sqlalchemy[asyncio]>=2.0.25 asyncpg>=0.29.0
alembic>=1.13.0             psycopg2-binary>=2.9.0
python-gitlab>=4.4.0        docker>=7.0.0
httpx>=0.26.0               PyJWT[crypto]>=2.8.0
cffi>=1.17.0                python-dotenv>=1.0.0
pydantic>=2.5.0             pydantic-settings>=2.1.0
python-multipart>=0.0.6     loguru>=0.7.0
```

**测试** (`backend/requirements-test.txt`)：
```
pytest>=7.4.0               pytest-asyncio>=0.23.0
pytest-cov>=4.1.0           pytest-timeout>=2.2.0
requests>=2.31.0            aiosqlite>=0.19.0
```

**E2E 测试** (`backend/tests/e2e/requirements-e2e.txt`)：
```
pytest-playwright>=0.4.0    playwright>=1.40.0
pytest-html>=4.0.0          pytest-xdist>=3.5.0
playwright==1.52.0          (pinned for browser compatibility)
```

### 2.3 Node.js 依赖

见 `frontend/package.json`，共 16 个 production + 10 个 dev 依赖。
传递依赖约 800+ 包（通过 `package-lock.json` 锁定）。

### 2.4 特殊二进制

| 文件 | 来源 | 大小 | 用途 |
|------|------|------|------|
| `claude` | `https://claude.ai/install.sh` | ~217 MB | worker 容器内 AI 代码生成 |
| Chromium | Playwright `install chromium` | ~150 MB | E2E 浏览器测试（可选） |

### 2.5 系统 APT 包

已 bake 到各 Docker 镜像中（参见 Dockerfile.backend, Dockerfile.worker, Dockerfile.e2e）。
**如果只用预构建镜像，无需单独打包 APT 依赖。**

---

## 3. 在线环境打包（Phase A）

> 以下所有操作在**有互联网**的机器上执行。

### 3.1 准备工作目录

```bash
# 在项目根目录下创建打包输出目录
mkdir -p offline-bundle-dev/{images,python-wheels,node-deps,bin,source}
```

### 3.2 导出 Docker 镜像

```bash
# ① 先确保所有镜像已构建
cd deploy
docker compose build              # 构建 backend, nginx
docker build -f Dockerfile.worker -t codify-worker:latest ..  # 构建 worker
docker pull postgres:16-alpine    # 拉取 postgres

# ② 导出运行镜像（部署用）
docker save \
  codify-backend:latest \
  codify-nginx:latest \
  codify-worker:latest \
  postgres:16-alpine \
  | gzip -1 > ../offline-bundle-dev/images/codify-runtime-images.tar.gz

# ③ 导出基础镜像（可选 — 内网重新构建 Docker 镜像时需要）
docker save \
  ubuntu:22.04 \
  node:22-alpine \
  nginx:alpine \
  debian:bookworm-slim \
  python:3.11-slim \
  | gzip -1 > ../offline-bundle-dev/images/codify-base-images.tar.gz

# ④ 生成校验和
cd ../offline-bundle-dev/images
shasum -a 256 *.tar.gz > SHA256SUMS
```

### 3.3 下载 Python wheels

```bash
cd /path/to/project

# 目标平台参数（根据内网机器架构调整）
# 如果内网是 x86_64 Linux:
PLATFORM_ARGS="--platform manylinux2014_x86_64 --python-version 3.11 --only-binary=:all:"
# 如果和打包机同架构，省略 PLATFORM_ARGS

# ① 生产依赖
pip download \
  -r backend/requirements.txt \
  -d offline-bundle-dev/python-wheels/ \
  $PLATFORM_ARGS

# ② 测试依赖
pip download \
  -r backend/requirements-test.txt \
  -d offline-bundle-dev/python-wheels/ \
  $PLATFORM_ARGS

# ③ E2E 测试依赖
pip download \
  -r backend/tests/e2e/requirements-e2e.txt \
  -d offline-bundle-dev/python-wheels/ \
  $PLATFORM_ARGS

pip download \
  playwright==1.52.0 \
  -d offline-bundle-dev/python-wheels/ \
  $PLATFORM_ARGS

# ④ 锁定精确版本（推荐）
pip install -r backend/requirements.txt -r backend/requirements-test.txt
pip freeze > offline-bundle-dev/python-wheels/requirements.lock.txt
```

> **注意**：`psycopg2-binary` 和 `cffi` 等包含 C 扩展，wheels 是平台相关的。
> 如果打包机和内网机架构不同（如 arm64 打包给 x86_64 用），必须指定 `--platform`。

### 3.4 打包 Node.js 依赖

```bash
cd frontend

# ① 确保 node_modules 完整且与 lock 文件一致
npm ci

# ② 打包 node_modules（最可靠的离线方式）
tar czf ../offline-bundle-dev/node-deps/node_modules.tar.gz node_modules/

# ③ 同时保留 lock 文件（用于校验）
cp package-lock.json ../offline-bundle-dev/node-deps/
cp package.json ../offline-bundle-dev/node-deps/
```

### 3.5 提取特殊二进制

```bash
# ① Claude CLI
# 如果已在 worker 镜像中，从镜像提取：
docker create --name tmp-worker codify-worker:latest
docker cp tmp-worker:/usr/local/bin/claude offline-bundle-dev/bin/claude
docker rm tmp-worker
chmod +x offline-bundle-dev/bin/claude

# 或直接下载：
# curl -fL https://claude.ai/install.sh | bash -s stable
# cp ~/.local/bin/claude offline-bundle-dev/bin/claude

# ② Playwright Chromium（可选 — 只有跑 E2E 才需要）
PLAYWRIGHT_BROWSERS_PATH=./offline-bundle-dev/bin/playwright-browsers \
  npx playwright install chromium
```

### 3.6 打包源码

```bash
# 方式 A: 整个 git 仓库
git clone --mirror /path/to/codify_observe offline-bundle-dev/source/codify_observe.git

# 方式 B: 简单 tar（如果不需要完整 git 历史）
tar czf offline-bundle-dev/source/codify-source.tar.gz \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  -C /path/to codify_observe/
```

### 3.7 添加脚本和文档

将本文档和辅助脚本一并放入 bundle（见后续章节的脚本内容）。

### 3.8 最终打包结构

```
offline-bundle-dev/
├── images/
│   ├── codify-runtime-images.tar.gz     (~2.5 GB)
│   ├── codify-base-images.tar.gz        (~1.0 GB, 可选)
│   └── SHA256SUMS
├── python-wheels/                        (~300 MB)
│   ├── fastapi-0.115.x-py3-none-any.whl
│   ├── uvicorn-0.34.x-py3-none-any.whl
│   ├── ... (所有 wheels, 含传递依赖)
│   └── requirements.lock.txt
├── node-deps/                            (~500 MB)
│   ├── node_modules.tar.gz
│   ├── package-lock.json
│   └── package.json
├── bin/
│   ├── claude                            (~217 MB)
│   └── playwright-browsers/              (~150 MB, 可选)
│       └── chromium-xxxx/
├── source/
│   └── codify_observe.git               (或 codify-source.tar.gz)
├── scripts/
│   ├── setup-dev.sh                      # 开发环境一键初始化
│   ├── load-and-deploy.sh                # 部署一键启动
│   └── verify-bundle.sh                  # 校验 bundle 完整性
├── config/
│   └── .env.offline.example              # 环境变量模板
└── README.md                             # 本文档
```

**用 tar 打最终包**：
```bash
tar czf codify-offline-bundle-$(date +%Y%m%d).tar.gz offline-bundle-dev/
```

---

## 4. 内网环境部署（Phase B）

> 以下操作在**内网目标机器**上执行。仅部署运行，无需开发环境。

### 4.1 解压 bundle

```bash
tar xzf codify-offline-bundle-YYYYMMDD.tar.gz
cd offline-bundle-dev
```

### 4.2 校验完整性

```bash
cd images && shasum -a 256 -c SHA256SUMS && cd ..
```

### 4.3 加载 Docker 镜像

```bash
echo "=== 加载运行镜像 ==="
gunzip -c images/codify-runtime-images.tar.gz | docker load

# 验证
docker images | grep -E 'codify-|postgres'
# 应看到：
#   codify-backend    latest    ...
#   codify-nginx      latest    ...
#   codify-worker     latest    ...
#   postgres          16-alpine ...
```

### 4.4 配置环境变量

```bash
# 使用已有的 offline-bundle 配置模板
cp deploy/offline-bundle/config/.env.offline.example deploy/offline-bundle/config/.env.offline

# 编辑填入实际值
vi deploy/offline-bundle/config/.env.offline
```

**关键配置项**：

```env
# === 必填 ===
GITLAB_URL=http://gitlab.internal:8080         # 内网 GitLab 地址
GITLAB_BOT_TOKEN=glpat-xxxxx                   # GitLab Bot Token

ANTHROPIC_BASE_URL=http://llm-gateway:8080/v1  # 内网 LLM API 端点
ANTHROPIC_API_KEY=sk-xxxxx                     # LLM API Key
ANTHROPIC_MODEL=claude-sonnet-4-20250514       # 模型标识

SECRET_KEY=生成一个随机字符串
SESSION_SECRET=再生成一个随机字符串
CONFIG_ENCRYPTION_KEY=32字节以上随机字符串

POSTGRES_USER=codify
POSTGRES_DB=codify
POSTGRES_PASSWORD=强密码
DATABASE_URL=postgresql+asyncpg://codify:强密码@postgres:5432/codify

BACKEND_URL=http://codify-host:8000
FRONTEND_URL=http://codify-host:8880
WORKER_IMAGE=codify-worker:latest

# === 内网自签证书（如需要）===
CUSTOM_CA_BUNDLE=/etc/ssl/certs/custom-ca.crt
WORKER_CA_CERT_HOST_PATH=/opt/ca.crt           # 宿主机上 CA 证书路径
```

### 4.5 自签证书处理（如需要）

如果内网 GitLab / LLM 网关使用自签 CA 证书：

```bash
# 将 CA 证书文件放到宿主机固定路径
sudo cp your-ca.crt /opt/ca.crt

# .env.offline 中设置：
# CUSTOM_CA_BUNDLE=/etc/ssl/certs/custom-ca.crt
# WORKER_CA_CERT_HOST_PATH=/opt/ca.crt
```

> **注意**：当前 `deploy/offline-bundle/docker-compose.yml` 缺少 CA 证书卷挂载。
> 需要在 backend 和 scheduler 服务的 `volumes:` 中添加：
> ```yaml
> - /opt/ca.crt:/etc/ssl/certs/custom-ca.crt:ro
> ```
> 以及在 scheduler 的 `environment:` 中添加：
> ```yaml
> - WORKER_CA_CERT_HOST_PATH=/opt/ca.crt
> - WORKER_VOLUME_MOUNTS=${WORKER_VOLUME_MOUNTS:-}
> ```

### 4.6 启动服务

```bash
cd deploy/offline-bundle
./scripts/start.sh

# 或手动：
docker compose -f docker-compose.yml up -d
```

### 4.7 验证部署

```bash
# 健康检查
./scripts/health-check.sh

# 手动验证
curl -s http://localhost:8000/health       # 应返回 200
curl -s -o /dev/null -w '%{http_code}' http://localhost:8880/  # 应返回 200

# 检查日志
docker logs codify-backend --tail 20
docker logs codify-scheduler --tail 20

# 检查数据库迁移
docker exec codify-postgres psql -U codify -d codify -c "SELECT version_num FROM alembic_version;"
```

---

## 5. 内网开发环境搭建（Phase C）

> 在内网机器上进行代码开发、单元测试、前端构建。

### 5.1 解压源码

```bash
# 如果用 git bare repo:
git clone offline-bundle-dev/source/codify_observe.git codify_observe
cd codify_observe

# 如果用 tar:
tar xzf offline-bundle-dev/source/codify-source.tar.gz
cd codify_observe
```

### 5.2 后端 Python 环境

```bash
cd backend

# 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 离线安装生产依赖
pip install --no-index \
  --find-links=../offline-bundle-dev/python-wheels/ \
  -r requirements.txt

# 离线安装测试依赖
pip install --no-index \
  --find-links=../offline-bundle-dev/python-wheels/ \
  -r requirements-test.txt

# 验证
python -c "import fastapi; import sqlalchemy; import uvicorn; print('OK')"
pytest --version
```

### 5.3 前端 Node.js 环境

```bash
cd frontend

# 方式 A（推荐）：直接解压预打包的 node_modules
tar xzf ../offline-bundle-dev/node-deps/node_modules.tar.gz

# 方式 B：用离线 npm cache
# npm ci --offline --cache ../offline-bundle-dev/node-deps/npm-cache

# 验证
npx vue-tsc --version
npm run build    # 应能成功构建
```

### 5.4 运行测试

```bash
# 后端单元测试
cd backend
source .venv/bin/activate
pytest tests/unit/ -v

# 后端 mock E2E 测试（不需要外部服务）
pytest tests/mock_e2e/ -v

# 前端单元测试
cd frontend
npx vitest run

# 前端类型检查 + 构建
npm run build
```

### 5.5 本地开发服务器

```bash
# 后端（需要 PostgreSQL — 可用 Docker 部署的 postgres）
cd backend
export DATABASE_URL=postgresql+asyncpg://codify:codify_password@localhost:5432/codify
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm run dev
```

### 5.6 一键初始化脚本

以下脚本可放入 `scripts/setup-dev.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/.."
PROJECT_DIR="${BUNDLE_DIR}/source/codify_observe"

echo "=== [1/4] 加载 Docker 镜像 ==="
gunzip -c "${BUNDLE_DIR}/images/codify-runtime-images.tar.gz" | docker load

echo "=== [2/4] 安装 Python 依赖 ==="
cd "${PROJECT_DIR}/backend"
python3.11 -m venv .venv
source .venv/bin/activate
pip install --no-index \
  --find-links="${BUNDLE_DIR}/python-wheels/" \
  -r requirements.txt \
  -r requirements-test.txt

echo "=== [3/4] 安装 Node.js 依赖 ==="
cd "${PROJECT_DIR}/frontend"
tar xzf "${BUNDLE_DIR}/node-deps/node_modules.tar.gz"

echo "=== [4/4] 验证 ==="
cd "${PROJECT_DIR}/backend"
source .venv/bin/activate
python -c "import fastapi; print('Python deps OK')"
cd "${PROJECT_DIR}/frontend"
npx vue-tsc --version && echo "Node deps OK"

echo ""
echo "✅ 开发环境初始化完成！"
echo ""
echo "后端开发：cd backend && source .venv/bin/activate && pytest"
echo "前端开发：cd frontend && npm run dev"
echo "Docker 部署：cd deploy/offline-bundle && ./scripts/start.sh"
```

---

## 6. 内网 Docker 镜像重新构建（Phase D）

> **适用场景**：在内网修改代码后，需要重新构建 Docker 镜像进行部署。

### 6.1 加载基础镜像

```bash
gunzip -c offline-bundle-dev/images/codify-base-images.tar.gz | docker load

# 验证
docker images | grep -E 'ubuntu|node|nginx|debian|python'
```

### 6.2 Backend 镜像离线构建

需要修改 `Dockerfile.backend` 使 pip install 使用本地 wheels：

```bash
# 将 wheels 目录放到构建上下文中
cp -r offline-bundle-dev/python-wheels/ backend/offline-wheels/

# 构建时使用 build arg
docker build \
  -f deploy/Dockerfile.backend \
  --build-arg PIP_FIND_LINKS=/build/offline-wheels \
  --build-arg PIP_NO_INDEX=1 \
  -t codify-backend:latest .
```

或者修改 Dockerfile.backend 的 pip 行：

```dockerfile
# 离线模式：拷贝 wheels 并使用 --find-links
COPY backend/offline-wheels/ /tmp/wheels/
RUN /venv/bin/pip install --no-index --find-links=/tmp/wheels/ -r requirements.txt
```

### 6.3 Frontend 镜像离线构建

```bash
# 将 node_modules 放到前端目录
cd frontend
tar xzf ../offline-bundle-dev/node-deps/node_modules.tar.gz
cd ..

# 修改 Dockerfile.frontend 跳过 npm ci
docker build -f deploy/Dockerfile.frontend -t codify-nginx:latest .
```

修改 Dockerfile.frontend 的 npm 行：

```dockerfile
# 替换 npm ci 为直接使用预置的 node_modules
COPY frontend/ .
# 不再执行 npm ci —— node_modules 已在 COPY 中包含
RUN npx vite build
```

### 6.4 Worker 镜像离线构建

```bash
# 将 Claude CLI binary 放到构建上下文
mkdir -p deploy/offline-bin
cp offline-bundle-dev/bin/claude deploy/offline-bin/

# 构建
docker build -f deploy/Dockerfile.worker -t codify-worker:latest .
```

修改 Dockerfile.worker：

```dockerfile
# 替换在线下载 Claude CLI 为直接 COPY
FROM scratch AS claude-installer
COPY deploy/offline-bin/claude /usr/local/bin/claude

FROM python:3.11-slim
# ... 其余不变 ...
COPY --from=claude-installer /usr/local/bin/claude /usr/local/bin/claude
```

### 6.5 快速重建 Makefile 目标

在 Makefile 中添加离线构建 target（建议）：

```makefile
build-offline-backend:
	cp -r offline-bundle-dev/python-wheels backend/offline-wheels
	docker build -f deploy/Dockerfile.backend.offline -t codify-backend:latest .

build-offline-nginx:
	tar xzf offline-bundle-dev/node-deps/node_modules.tar.gz -C frontend/
	docker build -f deploy/Dockerfile.frontend.offline -t codify-nginx:latest .

build-offline-worker:
	docker build -f deploy/Dockerfile.worker.offline -t codify-worker:latest .

build-offline: build-offline-backend build-offline-nginx build-offline-worker
```

---

## 7. 特殊组件处理

### 7.1 Claude CLI

**Claude CLI 是一个自包含二进制**，约 217 MB。

- 打包方式：从 worker 镜像提取或在线环境下载
- 内网使用：COPY 到 worker 容器中
- 更新方式：每次更新需在有网环境重新下载并替换

**Claude CLI 本身需要网络调用 Anthropic API**，在内网必须配置 `ANTHROPIC_BASE_URL` 指向内网 LLM 端点。Worker 容器 entrypoint 会自动将此环境变量传递给 Claude CLI。

### 7.2 Playwright / Chromium（E2E 测试）

仅在需要运行 E2E 浏览器测试时才需要。

```bash
# 内网安装 playwright 包
pip install --no-index --find-links=python-wheels/ playwright==1.52.0

# 设置浏览器路径并使用预下载的浏览器
export PLAYWRIGHT_BROWSERS_PATH=/path/to/offline-bundle-dev/bin/playwright-browsers
# playwright 会自动找到该路径下的 chromium
```

> 如果不需要 E2E 测试，可以完全跳过 Playwright 相关内容。

### 7.3 Maven 仓库缓存

Worker 容器可能需要构建 Java/Maven 项目。Maven 默认从 Maven Central 下载依赖。

**方案 A：预热 .m2 仓库**（推荐）
```bash
# 在有网环境针对目标项目执行一次构建
mvn dependency:go-offline -f /path/to/target-project/pom.xml

# 打包 .m2 仓库
tar czf offline-bundle-dev/maven-repo.tar.gz -C ~/.m2 repository/
```

内网配置：
```env
# .env.offline 中设置
WORKER_VOLUME_MOUNTS=[{"host_path":"/opt/maven-repo","container_path":"/home/codify/.m2/repository","mode":"rw"}]
```

```bash
# 解压到宿主机
sudo mkdir -p /opt/maven-repo
sudo tar xzf offline-bundle-dev/maven-repo.tar.gz -C /opt/maven-repo
```

**方案 B：内网 Maven 私服**（Nexus/Artifactory）
如果内网有 Maven 私服，在 `WORKER_VOLUME_MOUNTS` 中把宿主机上的
`settings.xml` 挂载到 `/home/codify/.m2/settings.xml`。

### 7.4 自签 CA 证书

内网环境通常使用自签 CA。Codify 通过 `CUSTOM_CA_BUNDLE` 环境变量统一处理，
自动为以下组件信任 CA：

| 组件 | 机制 |
|------|------|
| 系统 (curl/wget) | `update-ca-certificates` |
| Git | `http.sslCAInfo` |
| Python (httpx/requests) | `REQUESTS_CA_BUNDLE` + `SSL_CERT_FILE` |
| Node.js / Claude CLI | `NODE_EXTRA_CA_CERTS` |
| JDK (Maven/Gradle) | `keytool -importcert` |

**配置步骤**：
1. 将 CA 证书文件放到宿主机 `/opt/ca.crt`
2. `.env.offline` 设置 `CUSTOM_CA_BUNDLE=/etc/ssl/certs/custom-ca.crt`
3. `.env.offline` 设置 `WORKER_CA_CERT_HOST_PATH=/opt/ca.crt`
4. `docker-compose.yml` 中为 backend 和 scheduler 挂载 CA 文件

---

## 8. 验证清单

### 8.1 部署验证

| # | 检查项 | 命令 | 预期结果 |
|---|--------|------|----------|
| 1 | 镜像加载 | `docker images \| grep codify` | 4 个镜像存在 |
| 2 | 服务启动 | `docker ps \| grep codify` | 4 个容器 running |
| 3 | 后端健康 | `curl http://HOST:8000/health` | 200 |
| 4 | 前端加载 | `curl -o /dev/null -w '%{http_code}' http://HOST:8880/` | 200 |
| 5 | 数据库迁移 | `docker exec codify-postgres psql -U codify -c "SELECT version_num FROM alembic_version;"` | 有版本号 |
| 6 | GitLab 连通 | Dashboard → 项目列表 | 能看到项目 |
| 7 | Worker 容器 | 创建测试任务 | 容器能启动并完成 |
| 8 | LLM 连通 | Worker 容器执行任务 | Claude CLI 能调用 API |

### 8.2 开发环境验证

| # | 检查项 | 命令 | 预期结果 |
|---|--------|------|----------|
| 1 | Python 依赖 | `python -c "import fastapi"` | 无报错 |
| 2 | 后端单元测试 | `cd backend && pytest tests/unit/ -q` | 全部通过 |
| 3 | Mock E2E 测试 | `cd backend && pytest tests/mock_e2e/ -q` | 全部通过 |
| 4 | 前端构建 | `cd frontend && npm run build` | 构建成功 |
| 5 | 前端测试 | `cd frontend && npx vitest run` | 全部通过 |

### 8.3 镜像重新构建验证

| # | 检查项 | 命令 | 预期结果 |
|---|--------|------|----------|
| 1 | Backend 镜像构建 | `docker build ...` | 构建成功 |
| 2 | Frontend 镜像构建 | `docker build ...` | 构建成功 |
| 3 | Worker 镜像构建 | `docker build ...` | 构建成功 |
| 4 | 重新部署 | `docker compose up -d` | 服务正常 |

---

## 9. 日常维护与更新流程

### 9.1 代码更新

```
有网环境                        内网环境
   │                              │
   │  git bundle create           │
   │  update.bundle               │
   │  ─────────────────────→      │
   │                     git pull from bundle
   │                              │
```

```bash
# 有网环境：生成增量包
git bundle create update-$(date +%Y%m%d).bundle origin/main ^last-transferred-commit

# 内网环境：应用
git bundle verify update-YYYYMMDD.bundle
git pull update-YYYYMMDD.bundle main
```

### 9.2 依赖更新

当 `requirements.txt` 或 `package.json` 变更时：

```bash
# 有网环境：重新下载 wheels/node_modules
pip download -r backend/requirements.txt -d new-wheels/
cd frontend && npm ci && tar czf new-node-modules.tar.gz node_modules/

# 传输到内网并替换
```

### 9.3 镜像更新

```bash
# 有网环境：重新构建 + 导出
docker compose build && docker save ... | gzip > new-images.tar.gz

# 内网环境：加载 + 重启
gunzip -c new-images.tar.gz | docker load
docker compose -f docker-compose.yml up -d
```

### 9.4 Claude CLI 更新

```bash
# 有网环境
curl -fL https://claude.ai/install.sh | bash -s stable
cp ~/.local/bin/claude /transfer/claude-new

# 内网：替换 binary 并重新构建 worker 镜像
cp /transfer/claude-new deploy/offline-bin/claude
docker build -f deploy/Dockerfile.worker.offline -t codify-worker:latest .
```

---

## 10. 故障排查

### Q: docker load 报错 "no space left on device"
**A**: 清理 Docker 未使用的镜像和容器：`docker system prune -a`

### Q: pip install --no-index 找不到某个包
**A**: 检查 wheels 目录中是否有该包及其所有传递依赖。重新在有网环境执行 `pip download` 确保完整。
常见遗漏：`setuptools`、`wheel`、`pip` 自身。

### Q: npm run build 报模块找不到
**A**: 确认 `node_modules.tar.gz` 是在相同 Node.js 大版本下打包的。
如果版本差异大，考虑用 `npm cache` 方式重新安装。

### Q: Worker 容器无法访问 GitLab
**A**: 检查：
1. `GITLAB_URL` 是否正确（内网地址）
2. Worker 容器 DNS 能否解析 GitLab 主机名
3. 如用自签证书，`CUSTOM_CA_BUNDLE` 和 `WORKER_CA_CERT_HOST_PATH` 是否已配置

### Q: Claude CLI 报 API 连接失败
**A**: 检查：
1. `ANTHROPIC_BASE_URL` 是否指向内网 LLM 端点
2. Worker 容器能否 curl 该端点：
   `docker exec <worker-container> curl -s $ANTHROPIC_BASE_URL/models`
3. 如用自签证书，确认 `NODE_EXTRA_CA_CERTS` 已生效

### Q: 前端 Dashboard 能打开但 API 请求全部 502
**A**: 检查 nginx → backend 的代理连通性：
```bash
docker exec codify-nginx curl -s http://backend:8000/health
```
如果失败，检查 Docker 网络和 backend 容器状态。

---

## 附录：已有 offline-bundle 待修复项

`deploy/offline-bundle/docker-compose.yml` 与主 `deploy/docker-compose.yml` 存在以下配置漂移，
建议在实施前修复：

| 缺失项 | 应添加位置 | 内容 |
|--------|-----------|------|
| CA 证书卷挂载 | backend + scheduler `volumes:` | `- /opt/ca.crt:/etc/ssl/certs/custom-ca.crt:ro`（或通过 env 变量化） |
| `WORKER_CA_CERT_HOST_PATH` | scheduler `environment:` | `WORKER_CA_CERT_HOST_PATH=${WORKER_CA_CERT_HOST_PATH:-}` |
| `WORKER_VOLUME_MOUNTS` | scheduler `environment:` | `WORKER_VOLUME_MOUNTS=${WORKER_VOLUME_MOUNTS:-}` |
| `.env.offline.example` 补充 | config/ | 添加 `WORKER_CA_CERT_HOST_PATH=` 和 `WORKER_VOLUME_MOUNTS=` |
