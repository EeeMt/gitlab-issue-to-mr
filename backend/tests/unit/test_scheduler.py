#!/usr/bin/env python3
"""Regression tests for scheduler split architecture.

Covers:
1. Web app lifespan should only init/close DB and never manage scheduler.
2. Standalone scheduler service should start and stop cleanly.
3. Threaded worker cleanup should dispose the DB engine before closing the loop.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


async def test_web_lifespan_is_api_only() -> None:
    """Ensure web lifespan does not start scheduler tasks anymore."""
    from app import main as app_main

    assert not hasattr(app_main, "start_scheduler"), "web module should not import scheduler control"
    assert not hasattr(app_main, "stop_scheduler"), "web module should not import scheduler control"

    with patch("app.main.init_db", new_callable=AsyncMock) as init_db_mock, patch(
        "app.main.close_db", new_callable=AsyncMock
    ) as close_db_mock, patch(
        "app.main.load_runtime_config_from_db", new_callable=AsyncMock
    ) as load_runtime_config_mock:
        async with app_main.lifespan(app_main.app):
            pass

        init_db_mock.assert_awaited_once()
        load_runtime_config_mock.assert_awaited_once()
        close_db_mock.assert_awaited_once()


async def test_scheduler_service_lifecycle() -> None:
    """Ensure standalone scheduler service orchestrates start/stop correctly."""
    from app import scheduler_service

    scheduler_stop_event = asyncio.Event()
    external_stop_event = asyncio.Event()
    external_stop_event.set()  # Trigger immediate shutdown path

    async def fake_start_scheduler() -> None:
        await scheduler_stop_event.wait()

    async def fake_stop_scheduler() -> None:
        scheduler_stop_event.set()

    with patch("app.scheduler_service.init_db", new_callable=AsyncMock) as init_db_mock, patch(
        "app.scheduler_service.close_db", new_callable=AsyncMock
    ) as close_db_mock, patch(
        "app.scheduler_service.load_runtime_config_from_db", new_callable=AsyncMock
    ) as load_runtime_config_mock, patch(
        "app.scheduler_service.start_scheduler", side_effect=fake_start_scheduler
    ) as start_scheduler_mock, patch(
        "app.scheduler_service.stop_scheduler", side_effect=fake_stop_scheduler
    ) as stop_scheduler_mock, patch(
        "app.scheduler_service.asyncio.Event", return_value=external_stop_event
        ):
        await scheduler_service.run_scheduler_service()

        init_db_mock.assert_awaited_once()
        load_runtime_config_mock.assert_awaited_once()
        close_db_mock.assert_awaited_once()
        start_scheduler_mock.assert_called_once()
        stop_scheduler_mock.assert_called_once()


def test_run_worker_task_disposes_engine_before_loop_close() -> None:
    """Ensure thread-local engine disposal runs on the same loop before close."""
    from app import scheduler as scheduler_module

    events = []

    class FakeEngine:
        async def dispose(self):
            events.append("dispose")

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeLoop:
        def __init__(self):
            self.closed = False

        def run_until_complete(self, coro):
            assert not self.closed
            events.append(coro.cr_code.co_name)
            return asyncio.run(coro)

        def close(self):
            events.append("close")
            self.closed = True

    fake_engine = FakeEngine()
    fake_loop = FakeLoop()
    fake_session_factory = MagicMock(return_value=FakeSessionContext())
    fake_worker = MagicMock()
    fake_worker.execute_task = AsyncMock(return_value=True)

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=fake_engine), patch(
        "sqlalchemy.ext.asyncio.async_sessionmaker", return_value=fake_session_factory
    ), patch("app.core.worker.WorkerExecutor", return_value=fake_worker), patch(
        "asyncio.new_event_loop", return_value=fake_loop
    ), patch("asyncio.set_event_loop"):
        result = scheduler_module._run_worker_task(123)

    assert result is True
    assert events[0] == "run_task"
    assert events[-1] == "close"
    assert events.count("dispose") == 2


async def _run() -> None:
    await test_web_lifespan_is_api_only()
    print("PASS: web lifespan is API-only")

    await test_scheduler_service_lifecycle()
    print("PASS: scheduler service lifecycle")

    test_run_worker_task_disposes_engine_before_loop_close()
    print("PASS: threaded worker engine cleanup")


if __name__ == "__main__":
    asyncio.run(_run())
    print("\nAll scheduler split tests passed")
