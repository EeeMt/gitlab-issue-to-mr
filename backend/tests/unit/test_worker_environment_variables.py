#!/usr/bin/env python3
"""Unit tests for worker environment variable helpers."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import get_settings  # noqa: E402
from app.core.config_crypto import encrypt_config_secret  # noqa: E402
from app.core.worker import WorkerExecutor  # noqa: E402
from app.core.worker_environment_variables import (  # noqa: E402
    RESERVED_WORKER_ENVIRONMENT_KEYS,
    build_worker_environment_map,
    deserialize_worker_environment_variable_value,
    list_worker_environment_variables,
    replace_worker_environment_variables,
    serialize_worker_environment_variable_for_api,
    serialize_worker_environment_variable_for_runtime,
    serialize_worker_environment_variable_value,
    validate_worker_environment_variable_key,
)
from app.models import WorkerEnvironmentVariable  # noqa: E402


class WorkerEnvironmentVariableHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()

    def tearDown(self) -> None:
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_validate_worker_environment_variable_key_accepts_uppercase_keys(self) -> None:
        self.assertEqual(
            validate_worker_environment_variable_key("CUSTOM_FLAG_1"),
            "CUSTOM_FLAG_1",
        )

    def test_validate_worker_environment_variable_key_rejects_lowercase_key(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\^\[A-Z_\]\[A-Z0-9_\]\*\$"):
            validate_worker_environment_variable_key("lowercase_key")

    def test_validate_worker_environment_variable_key_rejects_reserved_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved"):
            validate_worker_environment_variable_key("TASK_ID")

    def test_secret_api_serialization_hides_value(self) -> None:
        row = WorkerEnvironmentVariable(
            key="CUSTOM_SECRET",
            value="encrypted-value",
            is_secret=True,
        )

        serialized = serialize_worker_environment_variable_for_api(row)

        self.assertEqual(serialized["key"], "CUSTOM_SECRET")
        self.assertIsNone(serialized["value"])
        self.assertTrue(serialized["is_secret"])
        self.assertTrue(serialized["value_configured"])

    def test_runtime_serialization_marks_empty_plain_value_as_configured(self) -> None:
        row = WorkerEnvironmentVariable(
            id=12,
            key="EMPTY_PLAIN",
            value="",
            is_secret=False,
        )

        serialized = serialize_worker_environment_variable_for_runtime(row)

        self.assertEqual(serialized["id"], 12)
        self.assertEqual(serialized["value"], "")
        self.assertTrue(serialized["value_configured"])

    def test_runtime_map_decrypts_secret_values_and_preserves_empty_plain_values(self) -> None:
        secret_row = WorkerEnvironmentVariable(
            key="SECRET_TOKEN",
            value=encrypt_config_secret("super-secret"),
            is_secret=True,
        )
        empty_plain_row = WorkerEnvironmentVariable(
            key="EMPTY_VALUE",
            value="",
            is_secret=False,
        )

        runtime_map = build_worker_environment_map([secret_row, empty_plain_row])

        self.assertEqual(runtime_map["SECRET_TOKEN"], "super-secret")
        self.assertEqual(runtime_map["EMPTY_VALUE"], "")

    def test_secret_value_serialization_encrypts_before_storage_and_round_trips(self) -> None:
        serialized = serialize_worker_environment_variable_value("sk-secret", is_secret=True)

        self.assertNotEqual(serialized, "sk-secret")
        self.assertEqual(
            deserialize_worker_environment_variable_value(serialized, is_secret=True),
            "sk-secret",
        )

    @patch("app.core.worker.get_settings")
    def test_reserved_worker_keys_cover_emitted_optional_worker_env_keys(self, mock_get_settings) -> None:
        mock_get_settings.return_value = SimpleNamespace(
            gitlab_url="http://gitlab.example.com",
            gitlab_bot_token="test-token",
            anthropic_base_url="http://localhost:11434/v1",
            anthropic_api_key="test-key",
            anthropic_model="claude-sonnet-4-20250514",
            claude_max_turns=20,
            task_timeout=1800,
            custom_ca_bundle="/etc/ssl/custom-ca.crt",
        )
        worker = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        task = SimpleNamespace(
            project_id=123,
            user_prompt="Implement the task",
            id=456,
            initiator_display_name="Alice Zhang",
            initiator_email="alice@example.com",
            initiator_username="alice",
            task_mode="execute",
        )
        issue = SimpleNamespace(
            branch_name="task-123",
            id=789,
            title="Task title",
            claude_session_id="session-123",
            base_branch="develop",
        )
        provider = SimpleNamespace(
            id=None,
            api_key="provider-key",
            base_url="http://provider.example/v1",
            model="provider-model",
            max_turns=33,
            system_prompt="append this",
        )

        env = worker._build_container_env(
            task,
            issue,
            mr_iid=5,
            target_branch="main",
            provider=provider,
        )

        self.assertEqual(env["APPEND_SYSTEM_PROMPT"], "append this")
        self.assertEqual(env["RESUME_SESSION"], "session-123")
        self.assertEqual(env["BASE_BRANCH"], "develop")
        self.assertEqual(env["MR_IID"], "5")
        self.assertEqual(env["CUSTOM_CA_BUNDLE"], "/etc/ssl/custom-ca.crt")
        self.assertTrue(set(env).issubset(RESERVED_WORKER_ENVIRONMENT_KEYS))

    def test_codegraph_toggle_env_key_is_reserved(self) -> None:
        with self.assertRaises(ValueError):
            validate_worker_environment_variable_key("CODIFY_CODEGRAPH_ENABLED")

    @patch("app.core.worker.get_settings")
    def test_plan_mode_resumes_existing_issue_session(self, mock_get_settings) -> None:
        mock_get_settings.return_value = SimpleNamespace(
            gitlab_url="http://gitlab.example.com",
            gitlab_bot_token="test-token",
            anthropic_base_url="http://localhost:11434/v1",
            anthropic_api_key="test-key",
            anthropic_model="claude-sonnet-4-20250514",
            claude_max_turns=20,
            task_timeout=1800,
            custom_ca_bundle="",
        )
        worker = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        task = SimpleNamespace(
            project_id=123,
            user_prompt="Plan the implementation",
            id=456,
            initiator_display_name=None,
            initiator_email=None,
            initiator_username="alice",
            task_mode="plan",
        )
        issue = SimpleNamespace(
            branch_name="task-123",
            id=789,
            title="Task title",
            claude_session_id="session-123",
            base_branch=None,
        )
        provider = SimpleNamespace(
            id=None,
            api_key="provider-key",
            base_url="http://provider.example/v1",
            model="provider-model",
            max_turns=33,
            system_prompt=None,
        )

        env = worker._build_container_env(
            task,
            issue,
            mr_iid=None,
            target_branch="main",
            provider=provider,
        )

        self.assertEqual(env["TASK_MODE"], "plan")
        self.assertEqual(env["RESUME_SESSION"], "session-123")

    @patch("app.core.worker.get_settings")
    def test_fresh_session_mode_disables_issue_session_resume(self, mock_get_settings) -> None:
        mock_get_settings.return_value = SimpleNamespace(
            gitlab_url="http://gitlab.example.com",
            gitlab_bot_token="test-token",
            anthropic_base_url="http://localhost:11434/v1",
            anthropic_api_key="test-key",
            anthropic_model="claude-sonnet-4-20250514",
            claude_max_turns=20,
            task_timeout=1800,
            custom_ca_bundle="",
        )
        worker = WorkerExecutor(docker_client=MagicMock(), gitlab_client=MagicMock())
        task = SimpleNamespace(
            project_id=123,
            user_prompt="Start without conversation history",
            id=456,
            initiator_display_name=None,
            initiator_email=None,
            initiator_username="alice",
            task_mode="execute",
            session_mode="fresh",
        )
        issue = SimpleNamespace(
            branch_name="task-123",
            id=789,
            title="Task title",
            claude_session_id="session-123",
            base_branch=None,
        )
        provider = SimpleNamespace(
            id=None,
            api_key="provider-key",
            base_url="http://provider.example/v1",
            model="provider-model",
            max_turns=33,
            system_prompt=None,
        )

        env = worker._build_container_env(
            task,
            issue,
            mr_iid=None,
            target_branch="main",
            provider=provider,
        )

        self.assertEqual(env["START_FRESH_SESSION"], "1")
        self.assertNotIn("RESUME_SESSION", env)


class WorkerEnvironmentVariableQueryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(WorkerEnvironmentVariable.__table__.create)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    async def test_list_worker_environment_variables_returns_rows_sorted_by_key(self) -> None:
        async with self.session_factory() as db:
            db.add_all(
                [
                    WorkerEnvironmentVariable(key="ZETA_TOKEN", value="zeta", is_secret=False),
                    WorkerEnvironmentVariable(key="ALPHA_TOKEN", value="alpha", is_secret=False),
                    WorkerEnvironmentVariable(key="MIDDLE_TOKEN", value="middle", is_secret=True),
                ]
            )
            await db.commit()

            rows = await list_worker_environment_variables(db)

        self.assertEqual(
            [row.key for row in rows],
            ["ALPHA_TOKEN", "MIDDLE_TOKEN", "ZETA_TOKEN"],
        )

    async def test_replace_worker_environment_variables_replaces_rows_and_preserves_existing_secret(self) -> None:
        async with self.session_factory() as db:
            db.add_all(
                [
                    WorkerEnvironmentVariable(
                        key="OLD_PLAIN",
                        value="old-plain",
                        is_secret=False,
                    ),
                    WorkerEnvironmentVariable(
                        key="SECRET_TOKEN",
                        value=serialize_worker_environment_variable_value("secret-1", is_secret=True),
                        is_secret=True,
                    ),
                ]
            )
            await db.commit()

            rows = await replace_worker_environment_variables(
                db,
                [
                    SimpleNamespace(key="PLAIN_TOKEN", value="plain-2", is_secret=False),
                    SimpleNamespace(key="SECRET_TOKEN", value="", is_secret=True),
                ],
            )
            await db.commit()

            refreshed_rows = await list_worker_environment_variables(db)

        self.assertEqual([row.key for row in rows], ["PLAIN_TOKEN", "SECRET_TOKEN"])
        self.assertEqual([row.key for row in refreshed_rows], ["PLAIN_TOKEN", "SECRET_TOKEN"])
        self.assertEqual(refreshed_rows[0].value, "plain-2")
        self.assertFalse(refreshed_rows[0].is_secret)
        self.assertEqual(
            deserialize_worker_environment_variable_value(
                refreshed_rows[1].value,
                is_secret=refreshed_rows[1].is_secret,
            ),
            "secret-1",
        )

    async def test_replace_worker_environment_variables_rejects_duplicate_keys(self) -> None:
        async with self.session_factory() as db:
            with self.assertRaisesRegex(ValueError, "Duplicate worker environment variable key"):
                await replace_worker_environment_variables(
                    db,
                    [
                        SimpleNamespace(key="DUPLICATE_KEY", value="one", is_secret=False),
                        SimpleNamespace(key="DUPLICATE_KEY", value="two", is_secret=False),
                    ],
                )

    async def test_replace_worker_environment_variables_rejects_new_blank_secret(self) -> None:
        async with self.session_factory() as db:
            with self.assertRaisesRegex(ValueError, "blank value"):
                await replace_worker_environment_variables(
                    db,
                    [SimpleNamespace(key="NEW_SECRET", value="", is_secret=True)],
                )


if __name__ == "__main__":
    unittest.main()
