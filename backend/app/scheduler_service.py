"""Standalone scheduler service entry point."""

import asyncio
import logging
import signal

from app.config import get_settings
from app.core.ci_failure_collector import start_ci_failure_collector
from app.database import close_db, init_db
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

    # Run migrations first
    run_migrations()

    await init_db()
    await load_runtime_config_from_db()
    stop_event = asyncio.Event()

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

    await close_db()
    logger.info("Scheduler service stopped")


def main() -> None:
    """Sync entrypoint for docker command execution."""
    asyncio.run(run_scheduler_service())


if __name__ == "__main__":
    main()
