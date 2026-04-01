# 日志追踪方案

本文档描述如何实现前后端全链路日志追踪，便于快速定位线上问题。

## 概述

当用户报告问题时，通过 Trace ID 可快速定位相关日志。

### 核心机制

- 每个 HTTP 请求分配唯一 Trace ID（8位短码）
- Trace ID 贯穿请求生命周期
- 日志按 Trace ID 归档
- 响应头和错误响应都返回 Trace ID
- 前端可随时获取当前 Trace ID

### 效果示例

```
用户操作 → 前端显示 "操作失败 (ID: a1b2c3d4)"
   ↓
后端日志: [a1b2c3d4] → GET /api/tasks
后端日志: [a1b2c3d4] ← 500 Error: Validation failed
   ↓
运维: grep "a1b2c3d4" logs/app_2026-04-01.log
```

---

## 后端实现

### 1.1 安装依赖

```bash
pip install loguru
```

### 1.2 创建日志配置

`backend/app/core/logging.py`

```python
"""
日志配置模块
"""
import sys
from pathlib import Path
from loguru import logger
import datetime

# 日志目录
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 保留天数
RETENTION_DAYS = 7


def setup_logging():
    """
    配置 Loguru 日志系统

    - 控制台输出：彩色友好格式
    - 文件输出：JSON 格式，便于检索
    """
    # 移除默认 handler
    logger.remove()

    # 控制台输出（开发环境）
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[trace_id]:‑8}</cyan> | <level>{message}</level>",
        colorize=True,
    )

    # 文件输出（JSON 格式）
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"app_{today}.log"

    logger.add(
        str(log_file),
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[trace_id]:‑8} | {message}",
        rotation="00:00",  # 每天零点轮转
        retention=f"{RETENTION_DAYS} days",  # 保留7天
        serialize=True,  # JSON 格式
        enqueue=True,  # 异步写入
    )

    logger.info("日志系统初始化完成")


def get_logger(name: str = None):
    """
    获取带有 trace_id 上下文的 logger

    用法:
        logger = get_logger()
        logger.info("这是一条日志")  # 自动带上 trace_id
    """
    if name:
        return logger.bind(name=name)
    return logger


class LoggerContext:
    """
    日志上下文管理器

    用法:
        with LoggerContext(trace_id="abc123"):
            logger.info("这条日志带有 trace_id")
    """
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.token = None

    def __enter__(self):
        self.token = logger.configure(extra=self.kwargs)
        return self

    def __exit__(self, *args):
        logger.configure(extra={})
        if self.token:
            try:
                logger.remove(self.token)
            except ValueError:
                pass  # 可能已自动移除
```

### 1.3 创建 Trace 中间件

`backend/app/middleware/trace.py`

```python
"""
Trace ID 中间件

每个请求自动分配 Trace ID，记录请求完整生命周期
"""
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import get_logger


class TraceMiddleware(BaseHTTPMiddleware):
    """
    Trace ID 中间件

    功能:
    1. 优先使用请求头中的 X-Trace-ID（支持链路追踪）
    2. 否则自动生成 8 位短码
    3. 记录完整请求日志
    4. 响应头返回 Trace ID
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.logger = get_logger("trace")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. 获取或生成 Trace ID
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())[:8]

        # 2. 记录请求开始
        self.logger.info(
            f"→ {request.method} {request.url.path}",
            extra={"trace_id": trace_id}
        )

        # 3. 记录开始时间
        start_time = time.time()

        # 4. 将 trace_id 存入 request.state（后续可直接获取）
        request.state.trace_id = trace_id

        # 5. 执行请求
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # 6. 记录请求完成
            status_code = response.status_code
            log_level = "INFO" if status_code < 400 else "WARNING"

            self.logger.opt(level=log_level).info(
                f"← {status_code} ({duration_ms:.0f}ms)",
                extra={"trace_id": trace_id}
            )

            # 7. 响应头添加 Trace ID
            response.headers["X-Trace-ID"] = trace_id

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # 8. 记录异常
            self.logger.error(
                f"✗ {type(e).__name__}: {str(e)} ({duration_ms:.0f}ms)",
                extra={"trace_id": trace_id}
            )

            # 重新抛出，让异常处理器处理
            raise


def get_trace_id(request: Request) -> str:
    """
    从请求中获取 Trace ID

    用法:
        @app.get("/example")
        async def example(request: Request):
            trace_id = get_trace_id(request)
            logger.info(f"处理请求", extra={"trace_id": trace_id})
    """
    return getattr(request.state, 'trace_id', 'unknown')
```

### 1.4 更新 main.py

`backend/app/main.py`

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import setup_logging, get_logger
from app.middleware.trace import TraceMiddleware, get_trace_id

# 初始化日志
setup_logging()
logger = get_logger("main")

app = FastAPI(title="GIMR API")

# 注册 Trace 中间件
app.add_middleware(TraceMiddleware)

# CORS（如果需要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一异常处理
@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    trace_id = get_trace_id(request)

    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
        extra={"trace_id": trace_id}
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "trace_id": trace_id,
            "type": type(exc).__name__,
        }
    )


@app.get("/api/health")
async def health_check(request: Request):
    return {
        "status": "healthy",
        "trace_id": get_trace_id(request)
    }
```

### 1.5 业务代码中使用

```python
from app.middleware.trace import get_trace_id

@app.post("/api/tasks")
async def create_task(request: Request, task_data: TaskCreate):
    trace_id = get_trace_id(request)
    logger = get_logger("tasks")

    logger.info(
        f"创建任务: {task_data.title}",
        extra={"trace_id": trace_id}
    )

    try:
        task = await task_service.create(task_data)
        logger.info(f"任务创建成功: {task.id}", extra={"trace_id": trace_id})
        return task
    except Exception as e:
        logger.error(f"任务创建失败: {e}", extra={"trace_id": trace_id})
        raise
```

---

## 前端实现

### 2.1 创建拦截器

`frontend/src/api/interceptors.ts`

```typescript
/**
 * API 拦截器
 *
 * 功能:
 * 1. 自动传递 Trace ID 到后端
 * 2. 响应中提取 Trace ID
 * 3. 错误时保存 Trace ID 供调试使用
 */

import axios, { AxiosError, AxiosResponse } from 'axios'

// 最后一次成功的 Trace ID
let lastTraceId = ''

// 创建 axios 实例
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 如果有上次的 Trace ID，传递下去（支持链路追踪）
    if (lastTraceId) {
      config.headers['X-Trace-ID'] = lastTraceId
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response: AxiosResponse) => {
    // 从响应头提取 Trace ID
    const traceId = response.headers['x-trace-id']
    if (traceId) {
      lastTraceId = traceId
      // 暴露到全局，便于调试
      window.__lastTraceId = traceId
    }
    return response
  },
  async (error: AxiosError) => {
    // 从错误响应中提取 Trace ID
    const traceId =
      error.response?.headers?.['x-trace-id'] ||
      (error.response?.data as any)?.trace_id ||
      lastTraceId ||
      'unknown'

    // 保存到全局
    window.__lastTraceId = traceId
    window.__lastError = {
      message: (error.response?.data as any)?.error || error.message,
      traceId,
      timestamp: new Date().toISOString(),
      status: error.response?.status,
    }

    return Promise.reject({
      ...error,
      traceId,
      trace_id: traceId,  // 兼容两种写法
    })
  }
)

// 导出 api 实例和工具函数
export { api, getLastTraceId, getLastError }

export function getLastTraceId(): string {
  return lastTraceId
}

export function getLastError(): {
  message: string
  traceId: string
  timestamp: string
  status?: number
} | null {
  return (window as any).__lastError || null
}

// 类型声明（可选，用于 IDE 提示）
declare global {
  interface Window {
    __lastTraceId?: string
    __lastError?: {
      message: string
      traceId: string
      timestamp: string
      status?: number
    }
  }
}
```

### 2.2 创建错误提示组件

`frontend/src/components/ErrorToast.vue`

```vue
<template>
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="visible" class="error-toast" @click="dismiss">
        <div class="error-toast__icon">⚠️</div>
        <div class="error-toast__content">
          <div class="error-toast__message">{{ message }}</div>
          <div class="error-toast__trace" @click.stop="copyTraceId">
            ID: {{ traceId }}
            <span class="error-toast__copy">(点击复制)</span>
          </div>
        </div>
        <button class="error-toast__close" @click.stop="dismiss">×</button>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { getLastError, getLastTraceId } from '../api/interceptors'

const visible = ref(false)
const message = ref('')
const traceId = ref('')

function showError() {
  const error = getLastError()
  if (error) {
    message.value = error.message || '操作失败'
    traceId.value = error.traceId
    visible.value = true

    // 3秒后自动消失
    setTimeout(() => {
      visible.value = false
    }, 5000)
  }
}

function dismiss() {
  visible.value = false
}

function copyTraceId() {
  navigator.clipboard.writeText(traceId.value)
  alert('Trace ID 已复制')
}

// 监听全局错误
watch(visible, (val) => {
  if (val) {
    // 重新获取最新的错误信息
    const error = getLastError()
    if (error) {
      message.value = error.message
      traceId.value = error.traceId
    }
  }
})

// 暴露显示方法
defineExpose({ showError })
</script>

<style scoped>
.error-toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
  z-index: 9999;
  max-width: 400px;
  cursor: pointer;
}

.error-toast__icon {
  font-size: 24px;
}

.error-toast__content {
  flex: 1;
}

.error-toast__message {
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
}

.error-toast__trace {
  font-size: 12px;
  color: #666;
  font-family: monospace;
}

.error-toast__copy {
  color: #1890ff;
  margin-left: 4px;
}

.error-toast__close {
  background: none;
  border: none;
  font-size: 20px;
  color: #999;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
```

### 2.3 全局错误处理

`frontend/src/main.ts`

```typescript
import { createApp } from 'vue'
import { createHeadClient } from '@unhead/vue'
import App from './App.vue'
import ErrorToast from './components/ErrorToast.vue'

const app = createApp(App)

// 全局错误提示组件
const errorToast = createApp(ErrorToast)
const errorToastMount = errorToast.mount(document.createElement('div'))
document.body.appendChild(errorToastMount.$el)

// 暴露到全局
;(window as any).__errorToast = errorToastMount

// 错误处理
app.config.errorHandler = (err, instance, info) => {
  console.error('Vue Error:', err, info)
}

// React 风格错误边界（如果使用）
// app.config.errorCaptured = ...

app.mount('#app')
```

### 2.4 调试面板（可选）

在页面右下角显示当前 Trace ID：

```vue
<template>
  <div v-if="traceId" class="trace-badge" @click="copy">
    🆔 {{ traceId }}
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getLastTraceId } from '../api/interceptors'

const traceId = ref('')

onMounted(() => {
  // 定期更新
  const update = () => {
    traceId.value = getLastTraceId()
  }
  update()
  setInterval(update, 1000)
})

function copy() {
  navigator.clipboard.writeText(traceId.value)
}
</script>

<style scoped>
.trace-badge {
  position: fixed;
  bottom: 16px;
  right: 16px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  font-size: 12px;
  font-family: monospace;
  border-radius: 6px;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.trace-badge:hover {
  opacity: 1;
}
</style>
```

---

## 日志查询

### 按 Trace ID 查询

```bash
# 单行命令
grep "a1b2c3d4" logs/app_2026-04-01.log

# 实时 tail
tail -f logs/app_2026-04-01.log | grep "a1b2c3d4"

# 跨多天查询
grep "a1b2c3d4" logs/app_2026-04-*.log
```

### 按时间范围查询

```bash
# 今天 10点到11点
grep "2026-04-01 1[01]:" logs/app_2026-04-01.log

# 某个用户的请求
grep "user_id=123" logs/app_2026-04-01.log | grep "a1b2c3d4"
```

### 日志分析脚本

`scripts/grep_logs.sh`

```bash
#!/bin/bash
# 按 Trace ID 查询日志

TRACE_ID=$1
LOG_DIR="logs"
DATE=${2:-$(date +%Y-%m-%d)}

if [ -z "$TRACE_ID" ]; then
    echo "用法: $0 <trace_id> [日期]"
    echo "示例: $0 a1b2c3d4 2026-04-01"
    exit 1
fi

LOG_FILE="${LOG_DIR}/app_${DATE}.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "日志文件不存在: $LOG_FILE"
    exit 1
fi

echo "=== Trace ID: $TRACE_ID | 日期: $DATE ==="
grep "$TRACE_ID" "$LOG_FILE" | jq '.' 2>/dev/null || grep "$TRACE_ID" "$LOG_FILE"
```

---

## 文件清单

### 后端

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/requirements.txt` | 修改 | 添加 loguru |
| `backend/app/core/logging.py` | 新增 | 日志配置模块 |
| `backend/app/middleware/trace.py` | 新增 | Trace ID 中间件 |
| `backend/app/main.py` | 修改 | 注册中间件、统一异常处理 |
| `backend/logs/.gitkeep` | 新增 | 日志目录占位 |

### 前端

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/api/interceptors.ts` | 新增 | API 拦截器 |
| `frontend/src/components/ErrorToast.vue` | 新增 | 错误提示组件 |
| `frontend/src/components/TraceBadge.vue` | 新增 | 调试面板（可选） |
| `frontend/src/main.ts` | 修改 | 全局错误处理 |

### 运维

| 文件 | 操作 | 说明 |
|------|------|------|
| `.gitignore` | 修改 | 忽略 `*.log` |
| `scripts/grep_logs.sh` | 新增 | 日志查询脚本 |

---

## 实施顺序

```
1. 后端基础
   ├── 1.1 安装 loguru
   ├── 1.2 创建 logging.py
   ├── 1.3 创建 trace.py
   └── 1.4 更新 main.py

2. 前端基础
   ├── 2.1 创建 interceptors.ts
   ├── 2.2 创建 ErrorToast.vue
   └── 2.3 更新 main.ts

3. 收尾
   ├── 3.1 创建 logs/.gitkeep
   ├── 3.2 更新 .gitignore
   └── 3.3 创建日志查询脚本
```

---

## 示例输出

### 后端日志（JSON 格式）

```json
{"time": "2026-04-01 12:00:00", "level": "INFO", "trace_id": "a1b2c3d4", "message": "→ POST /api/tasks"}
{"time": "2026-04-01 12:00:01", "level": "INFO", "trace_id": "a1b2c3d4", "message": "任务创建成功: 123"}
{"time": "2026-04-01 12:00:01", "level": "INFO", "trace_id": "a1b2c3d4", "message": "← 201 (150ms)"}
{"time": "2026-04-01 12:00:05", "level": "WARNING", "trace_id": "e5f6g7h8", "message": "← 400 (50ms)"}
{"time": "2026-04-01 12:00:10", "level": "ERROR", "trace_id": "i9j0k1l2", "message": "✗ ValueError: invalid input"}
```

### 前端错误提示

```
┌─────────────────────────────────────┐
│ ⚠️ 请求失败                           │
│ ID: a1b2c3d4 (点击复制)              │
└─────────────────────────────────────┘
```

### 运维查询

```bash
$ ./scripts/grep_logs.sh a1b2c3d4
=== Trace ID: a1b2c3d4 | 日期: 2026-04-01 ===
{"time": "2026-04-01 12:00:00", "level": "INFO", "trace_id": "a1b2c3d4", "message": "→ POST /api/tasks"}
{"time": "2026-04-01 12:00:01", "level": "INFO", "trace_id": "a1b2c3d4", "message": "← 201 (150ms)"}
```
