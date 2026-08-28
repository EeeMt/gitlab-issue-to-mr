"""Standalone scheduler service entry point."""

import asyncio
import logging
import signal

import uvicorn
from fastapi import FastAPI

from app.config import get_effective_settings, get_settings
from app.core.ci_failure_collector import start_ci_failure_collector
from app.core.docker_client import close_docker_clients
from app.core.harness_execution_policy import require_explicit_harness_execution_mode
from app.core.task_prompt import backfill_active_task_prompts
from app.database import AsyncSessionLocal, close_db, init_db
from app.migrations import run_migrations
from app.runtime_config import load_runtime_config_from_db
from app.scheduler import start_scheduler, stop_scheduler

settings = get_settings()

# Keep logging format aligned with web service.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run_scheduler_service() -> None:
    """Run scheduler as a dedicated process."""
    logger.info("Starting scheduler service...")
    require_explicit_harness_execution_mode(settings)

    # Run migrations first
    run_migrations()

    await init_db()
    await load_runtime_config_from_db()
    async with AsyncSessionLocal() as db:
        backfilled = await backfill_active_task_prompts(db, get_effective_settings())
    logger.info("Active task prompt backfill completed: %s task(s)", backfilled)
    stop_event = asyncio.Event()

    # Plan §4.8: the Scheduler must expose its execution mode for the
    # deployment preflight, which compares Backend/Scheduler /health payloads.
    health_app = FastAPI()

    @health_app.get("/health")
    async def _health() -> dict:
        return {
            "status": "running",
            "harness_execution_mode": get_settings().harness_execution_mode,
        }

    health_config = uvicorn.Config(
        health_app,
        host="0.0.0.0",
        port=settings.scheduler_health_port,
        # The scheduler health endpoint is HTTP-only. Avoid loading Uvicorn's
        # deprecated websockets implementation for a server with no WS route.
        ws="none",
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    health_server = uvicorn.Server(health_config)
    health_server.install_signal_handlers = lambda *a, **k: None
    health_task = asyncio.create_task(health_server.serve())
    logger.info(
        "Scheduler health endpoint listening on :%s (mode=%s)",
        settings.scheduler_health_port,
        get_settings().harness_execution_mode,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Signal handlers are not available on some platforms.
            pass

    scheduler_task = asyncio.create_task(start_scheduler())
    ci_collector_task = asyncio.create_task(start_ci_failure_collector(stop_event=stop_event))
    stop_waiter = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        {scheduler_task, ci_collector_task, stop_waiter},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if scheduler_task in done and scheduler_task.exception() is not None:
        raise scheduler_task.exception()
    if ci_collector_task in done and ci_collector_task.exception() is not None:
        raise ci_collector_task.exception()

    if stop_waiter in done:
        logger.info("Stop signal received, shutting down scheduler service...")
        await stop_scheduler()
        await scheduler_task
        await ci_collector_task

    for task in pending:
        task.cancel()

    health_server.should_exit = True
    await health_task

    close_docker_clients()
    await close_db()
    logger.info("Scheduler service stopped")


def main() -> None:
    """Sync entrypoint for docker command execution."""
    asyncio.run(run_scheduler_service())


if __name__ == "__main__":
    main()
