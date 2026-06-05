"""
日志配置模块
"""
import datetime
import os
import sys
from pathlib import Path

from loguru import logger

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
    - 日志级别通过环境变量 LOG_LEVEL 控制（默认 INFO）
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # 移除默认 handler
    logger.remove()

    # Set default extra values so format strings don't KeyError during startup
    logger.configure(extra={"trace_id": "--------"})

    # 控制台输出
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[trace_id]}</cyan> | <level>{message}</level>",
        colorize=True,
    )

    # 文件输出（JSON 格式）
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"app_{today}.log"

    logger.add(
        str(log_file),
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[trace_id]} | {message}",
        rotation="00:00",  # 每天零点轮转
        retention=f"{RETENTION_DAYS} days",  # 保留7天
        serialize=True,  # JSON 格式
        enqueue=True,  # 异步写入
    )

    logger.info("日志系统初始化完成，级别: {}", log_level)


def get_logger(name: str = None):
    """
    获取 logger
    """
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
