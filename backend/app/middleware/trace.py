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
        self.logger = get_logger()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. 获取或生成 Trace ID
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())[:8]

        # 2. 记录请求开始
        self.logger.bind(trace_id=trace_id).info(
            f"-> {request.method} {request.url.path}"
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
            if status_code >= 400:
                self.logger.bind(trace_id=trace_id).warning(
                    f"<- {status_code} ({duration_ms:.0f}ms)"
                )
            else:
                self.logger.bind(trace_id=trace_id).info(
                    f"<- {status_code} ({duration_ms:.0f}ms)"
                )

            # 7. 响应头添加 Trace ID
            response.headers["X-Trace-ID"] = trace_id

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # 8. 记录异常
            self.logger.bind(trace_id=trace_id).error(
                f"X {type(e).__name__}: {str(e)} ({duration_ms:.0f}ms)"
            )

            # 重新抛出，让异常处理器处理
            raise


def get_trace_id(request: Request) -> str:
    """
    从请求中获取 Trace ID
    """
    return getattr(request.state, 'trace_id', 'unknown')
