import unittest
from datetime import date

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models import TaskUsageLedger, UsageLimitPolicy


class UsageLimitModelsTests(unittest.TestCase):
    def test_usage_limit_policy_keeps_per_field_modes(self) -> None:
        policy = UsageLimitPolicy(
            scope_type="user",
            user_id=7,
            daily_tokens_mode="inherit",
            daily_tokens_value=None,
            weekly_tokens_mode="custom",
            weekly_tokens_value=500000,
            daily_tasks_mode="unlimited",
            daily_tasks_value=None,
            weekly_tasks_mode="custom",
            weekly_tasks_value=20,
        )

        self.assertEqual(policy.scope_type, "user")
        self.assertEqual(policy.weekly_tokens_value, 500000)
        self.assertEqual(policy.daily_tasks_mode, "unlimited")

    def test_task_usage_ledger_tracks_calendar_keys(self) -> None:
        ledger = TaskUsageLedger(
            task_id=11,
            user_id=7,
            task_status="completed",
            timezone_day=date(2026, 4, 27),
            timezone_week_start=date(2026, 4, 27),
            input_tokens=800,
            output_tokens=400,
            total_tokens=1200,
            task_count=1,
        )

        self.assertEqual(ledger.total_tokens, 1200)
        self.assertEqual(ledger.task_count, 1)

    def test_usage_limit_policy_has_single_system_default_constraint(self) -> None:
        policy_indexes = {index.name: index for index in UsageLimitPolicy.__table__.indexes}
        unique_constraint_names = {
            constraint.name
            for constraint in UsageLimitPolicy.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertIn("uq_usage_limit_policies_system_default", policy_indexes)
        self.assertIn("uq_usage_limit_policies_user_id", unique_constraint_names)
        system_default_index = policy_indexes["uq_usage_limit_policies_system_default"]

        self.assertTrue(system_default_index.unique)
        self.assertEqual(
            str(system_default_index.dialect_options["postgresql"]["where"]),
            "scope_type = 'system_default' AND user_id IS NULL",
        )
        self.assertEqual(
            str(system_default_index.dialect_options["sqlite"]["where"]),
            "scope_type = 'system_default' AND user_id IS NULL",
        )

    def test_task_usage_ledger_constrains_task_count_to_one(self) -> None:
        unique_constraint_names = {
            constraint.name
            for constraint in TaskUsageLedger.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        constraints = {
            constraint.name: constraint
            for constraint in TaskUsageLedger.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        }

        self.assertIn("uq_task_usage_ledger_task_id", unique_constraint_names)
        self.assertIn("ck_task_usage_ledger_task_count_is_one", constraints)
        self.assertEqual(
            str(constraints["ck_task_usage_ledger_task_count_is_one"].sqltext),
            "task_count = 1",
        )
