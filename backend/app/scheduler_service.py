"""Standalone scheduler service entry point."""

import asyncio
import logging
import signal

from app.config import get_settings
from app.database import close_db, init_db
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

    await init_db()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Signal handlers are not available on some platforms.
            pass

    scheduler_task = asyncio.create_task(start_scheduler())
    stop_waiter = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        {scheduler_task, stop_waiter},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if scheduler_task in done and scheduler_task.exception() is not None:
        raise scheduler_task.exception()

    if stop_waiter in done:
        logger.info("Stop signal received, shutting down scheduler service...")
        await stop_scheduler()
        await scheduler_task

    for task in pending:
        task.cancel()

    await close_db()
    logger.info("Scheduler service stopped")


def main() -> None:
    """Sync entrypoint for docker command execution."""
    asyncio.run(run_scheduler_service())


if __name__ == "__main__":
    main()
