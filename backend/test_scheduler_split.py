#!/usr/bin/env python3
"""Regression tests for scheduler split architecture.

Covers:
1. Web app lifespan should only init/close DB and never manage scheduler.
2. Standalone scheduler service should start and stop cleanly.
"""

import asyncio
from unittest.mock import AsyncMock, patch


async def test_web_lifespan_is_api_only() -> None:
    """Ensure web lifespan does not start scheduler tasks anymore."""
    from app import main as app_main

    assert not hasattr(app_main, "start_scheduler"), "web module should not import scheduler control"
    assert not hasattr(app_main, "stop_scheduler"), "web module should not import scheduler control"

    with patch("app.main.init_db", new_callable=AsyncMock) as init_db_mock, patch(
        "app.main.close_db", new_callable=AsyncMock
    ) as close_db_mock:
        async with app_main.lifespan(app_main.app):
            pass

        init_db_mock.assert_awaited_once()
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
        "app.scheduler_service.start_scheduler", side_effect=fake_start_scheduler
    ) as start_scheduler_mock, patch(
        "app.scheduler_service.stop_scheduler", side_effect=fake_stop_scheduler
    ) as stop_scheduler_mock, patch(
        "app.scheduler_service.asyncio.Event", return_value=external_stop_event
    ):
        await scheduler_service.run_scheduler_service()

        init_db_mock.assert_awaited_once()
        close_db_mock.assert_awaited_once()
        start_scheduler_mock.assert_called_once()
        stop_scheduler_mock.assert_called_once()


async def _run() -> None:
    await test_web_lifespan_is_api_only()
    print("PASS: web lifespan is API-only")

    await test_scheduler_service_lifecycle()
    print("PASS: scheduler service lifecycle")


if __name__ == "__main__":
    asyncio.run(_run())
    print("\nAll scheduler split tests passed")
