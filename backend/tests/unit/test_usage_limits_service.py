import unittest
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from app.core.usage_limits import (
    UsageLimitExceeded,
    UsageQuotaService,
    _calendar_keys_for_datetime,
    _next_reset_timestamps,
    upsert_task_usage_ledger,
)


class UsageQuotaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_effective_limits_loads_rows_from_db_when_overrides_absent(self) -> None:
        system_row = MagicMock(
            daily_tokens_mode="custom",
            daily_tokens_value=100000,
            weekly_tokens_mode="custom",
            weekly_tokens_value=500000,
            daily_tasks_mode="custom",
            daily_tasks_value=5,
            weekly_tasks_mode="custom",
            weekly_tasks_value=20,
        )
        user_row = MagicMock(
            daily_tokens_mode="inherit",
            daily_tokens_value=None,
            weekly_tokens_mode="custom",
            weekly_tokens_value=250000,
            daily_tasks_mode="unlimited",
            daily_tasks_value=None,
            weekly_tasks_mode="inherit",
            weekly_tasks_value=None,
        )
        system_result = MagicMock()
        system_result.scalar_one_or_none.return_value = system_row
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user_row
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[system_result, user_result])
        service = UsageQuotaService()

        limits = await service.resolve_effective_limits(db, user_id=7)

        self.assertEqual(db.execute.await_count, 2)
        self.assertEqual(limits["daily_tokens"].value, 100000)
        self.assertEqual(limits["weekly_tokens"].value, 250000)
        self.assertTrue(limits["daily_tasks"].is_unlimited)

    async def test_resolve_effective_limits_merges_system_and_user_modes(self) -> None:
        db = MagicMock()
        service = UsageQuotaService()

        limits = await service.resolve_effective_limits(
            db,
            user_id=7,
            system_row=MagicMock(
                daily_tokens_mode="custom",
                daily_tokens_value=100000,
                weekly_tokens_mode="custom",
                weekly_tokens_value=500000,
                daily_tasks_mode="custom",
                daily_tasks_value=5,
                weekly_tasks_mode="custom",
                weekly_tasks_value=20,
            ),
            user_row=MagicMock(
                daily_tokens_mode="inherit",
                daily_tokens_value=None,
                weekly_tokens_mode="custom",
                weekly_tokens_value=250000,
                daily_tasks_mode="unlimited",
                daily_tasks_value=None,
                weekly_tasks_mode="inherit",
                weekly_tasks_value=None,
            ),
        )

        self.assertEqual(limits["daily_tokens"].value, 100000)
        self.assertEqual(limits["weekly_tokens"].value, 250000)
        self.assertTrue(limits["daily_tasks"].is_unlimited)

    async def test_check_limits_raises_for_exceeded_item(self) -> None:
        db = MagicMock()
        service = UsageQuotaService()
        timezone = ZoneInfo("Asia/Shanghai")

        with self.assertRaises(UsageLimitExceeded) as ctx:
            await service.raise_if_over_limit(
                db,
                user_id=7,
                scope="create",
                now=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
                timezone=timezone,
                effective_limits={
                    "daily_tokens": MagicMock(is_unlimited=False, value=1000),
                },
                usage_totals={
                    "daily_tokens": 1200,
                },
            )

        self.assertEqual(ctx.exception.scope, "create")
        self.assertEqual(ctx.exception.exceeded_items[0]["metric"], "tokens")
        self.assertEqual(ctx.exception.exceeded_items[0]["reset_at"], "2026-04-29T00:00:00+08:00")

    def test_calendar_keys_follow_system_timezone_boundaries(self) -> None:
        timezone = ZoneInfo("Asia/Shanghai")

        day_key, week_key = _calendar_keys_for_datetime(
            datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            timezone=timezone,
        )

        self.assertEqual(day_key, date(2026, 4, 28))
        self.assertEqual(week_key, date(2026, 4, 27))

    def test_next_reset_timestamps_follow_calendar_boundaries(self) -> None:
        timezone = ZoneInfo("Asia/Shanghai")

        reset_at = _next_reset_timestamps(
            datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            timezone=timezone,
        )

        self.assertEqual(reset_at["daily"], "2026-04-29T00:00:00+08:00")
        self.assertEqual(reset_at["weekly"], "2026-05-04T00:00:00+08:00")

    async def test_upsert_task_usage_ledger_creates_new_row(self) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        task = MagicMock(
            id=11,
            initiator_user_id=7,
            status="completed",
            completed_at=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            input_tokens=800,
            output_tokens=400,
        )

        await upsert_task_usage_ledger(db, task, timezone=ZoneInfo("Asia/Shanghai"))

        added_row = db.add.call_args.args[0]
        self.assertEqual(added_row.task_id, 11)
        self.assertEqual(added_row.user_id, 7)
        self.assertEqual(added_row.total_tokens, 1200)
        self.assertEqual(added_row.timezone_day, date(2026, 4, 28))
        self.assertEqual(added_row.timezone_week_start, date(2026, 4, 27))

    async def test_upsert_task_usage_ledger_updates_existing_row(self) -> None:
        existing_row = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_row
        db = MagicMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.add = MagicMock()
        task = MagicMock(
            id=11,
            initiator_user_id=7,
            status="failed",
            completed_at=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            input_tokens=50,
            output_tokens=25,
        )

        await upsert_task_usage_ledger(db, task, timezone=ZoneInfo("Asia/Shanghai"))

        db.add.assert_not_called()
        self.assertEqual(existing_row.total_tokens, 75)
        self.assertEqual(existing_row.task_status, "failed")

    async def test_upsert_task_usage_ledger_skips_task_without_recorded_usage(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.add = MagicMock()
        task = MagicMock(
            id=11,
            initiator_user_id=7,
            status="completed",
            completed_at=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            input_tokens=None,
            output_tokens=None,
        )

        await upsert_task_usage_ledger(db, task, timezone=ZoneInfo("Asia/Shanghai"))

        db.execute.assert_not_awaited()
        db.add.assert_not_called()

    async def test_get_current_usage_totals_aggregates_daily_and_weekly_rows(self) -> None:
        daily_result = MagicMock()
        daily_result.one.return_value = (1200, 2)
        weekly_result = MagicMock()
        weekly_result.one.return_value = (5600, 5)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[daily_result, weekly_result])
        service = UsageQuotaService()

        totals = await service.get_current_usage_totals(
            db,
            user_id=7,
            now=datetime(2026, 4, 27, 16, 30, tzinfo=UTC),
            timezone=ZoneInfo("Asia/Shanghai"),
        )

        self.assertEqual(
            totals,
            {
                "daily_tokens": 1200,
                "weekly_tokens": 5600,
                "daily_tasks": 2,
                "weekly_tasks": 5,
            },
        )
