#!/usr/bin/env python3
"""Unit tests for Config Runtime API endpoints."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.config import get_settings, reset_runtime_config, set_runtime_config
from app.database import get_db
from app.dependencies.auth import require_authenticated_context
from app.main import app
from app.runtime_config import reset_runtime_config_sync_state


class ConfigRuntimeAPITests(unittest.TestCase):
    """Test /config/runtime API endpoints."""

    def setUp(self):
        self._original_config_encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config()
        reset_runtime_config_sync_state()

        self.client = TestClient(app)
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(all=MagicMock(return_value=[]))))
        self.mock_db.get = AsyncMock(return_value=None)
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        # Override require_authenticated_context to return a mock auth context
        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

    def tearDown(self):
        app.dependency_overrides.clear()
        reset_runtime_config()
        reset_runtime_config_sync_state()
        if self._original_config_encryption_key is None:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        else:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._original_config_encryption_key
        get_settings.cache_clear()

    def test_get_runtime_config_returns_current_settings(self):
        """GET /config/runtime should return current runtime configuration."""
        response = self.client.get("/api/config/runtime")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("max_concurrency", data)
        self.assertIn("task_timeout", data)
        self.assertIn("scheduler_interval", data)
        self.assertIn("default_target_branch", data)
        self.assertIn("max_retries", data)
        self.assertIn("retry_delay", data)
        self.assertIn("alert_on_failure", data)
        self.assertIn("anthropic_base_url", data)
        self.assertIn("anthropic_model", data)
        self.assertIn("claude_max_turns", data)

    def test_get_runtime_config_includes_worker_workspace_settings(self):
        """GET /config/runtime should expose persistent workspace settings."""
        response = self.client.get("/api/config/runtime")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("worker_workspace_host_path", data)
        self.assertIn("worker_workspace_retention_days", data)
        self.assertIn("worker_failed_workspace_retention_days", data)

    def test_runtime_config_includes_run_instruction_defaults(self):
        from app.core.task_prompt import BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE

        response = self.client.get("/api/config/runtime")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data["default_execute_run_instruction_template"],
            BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
        )
        self.assertIn("default_plan_run_instruction_template", data)
        self.assertIn("ci_auto_repair_run_instruction_template", data)

    def test_patch_run_instruction_template_independently(self):
        with patch(
            "app.api.config_runtime.load_runtime_config_from_db",
            new=AsyncMock(return_value=None),
        ):
            response = self.client.patch(
                "/api/config/runtime",
                json={"default_execute_run_instruction_template": "Execute {{user_prompt}}"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["default_execute_run_instruction_template"],
            "Execute {{user_prompt}}",
        )

    def test_invalid_run_instruction_template_is_not_persisted(self):
        for value in ("{{unknown}}", " \n", "x" * 50_001):
            with self.subTest(value_length=len(value)):
                self.mock_db.add.reset_mock()
                response = self.client.patch(
                    "/api/config/runtime",
                    json={"default_plan_run_instruction_template": value},
                )
                self.assertEqual(response.status_code, 422)
                self.mock_db.add.assert_not_called()

    def test_run_instruction_built_ins_are_admin_readable(self):
        from app.core.task_prompt import BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE

        response = self.client.get("/api/config/run-instruction-template-built-ins")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data["ci_auto_repair"]["content"],
            BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
        )
        self.assertNotIn("user_prompt", data["ci_auto_repair"]["available_placeholders"])

    def test_worker_workspace_host_path_defaults_to_issue_workspace_root(self):
        """Persistent issue workspace should be enabled by default."""
        from app.config import Settings

        settings = Settings()

        self.assertEqual(settings.worker_workspace_host_path, "/opt/codify-workspaces")

    def test_serialize_runtime_config_includes_worker_workspace_settings(self):
        from app.api.config_runtime import _serialize_runtime_config
        from app.config import Settings

        settings = Settings(
            worker_workspace_host_path="/opt/codify-workspaces",
            worker_workspace_retention_days=14,
            worker_failed_workspace_retention_days=30,
        )

        result = _serialize_runtime_config(settings)

        self.assertEqual(result.worker_workspace_host_path, "/opt/codify-workspaces")
        self.assertEqual(result.worker_workspace_retention_days, 14)
        self.assertEqual(result.worker_failed_workspace_retention_days, 30)

    def test_serialize_runtime_config_includes_worker_custom_scripts(self):
        from app.api.config_runtime import _serialize_runtime_config
        from app.config import Settings

        settings = Settings(
            worker_pre_script="echo pre",
            worker_post_script="echo post",
        )

        result = _serialize_runtime_config(settings)

        self.assertEqual(result.worker_pre_script, "echo pre")
        self.assertEqual(result.worker_post_script, "echo post")

    def test_patch_runtime_config_accepts_worker_custom_scripts(self):
        """PATCH /config/runtime should persist worker custom script fields."""
        with patch(
            "app.api.config_runtime.save_runtime_config_override",
            new=AsyncMock(),
        ) as mock_save:
            response = self.client.patch(
                "/api/config/runtime",
                json={
                    "worker_pre_script": "echo pre\nnpm ci",
                    "worker_post_script": "npm test\necho post",
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_save.assert_any_await(self.mock_db, "worker_pre_script", "echo pre\nnpm ci")
        mock_save.assert_any_await(self.mock_db, "worker_post_script", "npm test\necho post")

    def test_validate_worker_workspace_retention_days_bounds(self):
        from fastapi import HTTPException

        from app.api.config_runtime import _validate_config_value

        self.assertEqual(_validate_config_value("worker_workspace_retention_days", 14), 14)
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("worker_workspace_retention_days", -1)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_workspace_host_path_is_not_a_persisted_runtime_key(self):
        from app.config import get_runtime_config_types

        self.assertNotIn("worker_workspace_host_path", get_runtime_config_types())

    def test_patch_runtime_config_updates_max_concurrency(self):
        """PATCH /config/runtime should accept valid max_concurrency update.

        Note: Full persistence testing is done in test_runtime_config.py.
        This test verifies the endpoint accepts and validates the input.
        """
        response = self.client.patch(
            "/api/config/runtime",
            json={"max_concurrency": 5},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verify response contains expected fields
        self.assertIn("max_concurrency", data)

    def test_patch_runtime_config_updates_multiple_fields(self):
        """PATCH /config/runtime should accept multiple field updates.

        Note: Full persistence testing is done in test_runtime_config.py.
        This test verifies the endpoint accepts and validates all inputs.
        """
        response = self.client.patch(
            "/api/config/runtime",
            json={
                "max_concurrency": 10,
                "task_timeout": 3600,
                "default_target_branch": "develop",
                "anthropic_model": "claude-3-5-sonnet",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verify response contains expected fields
        self.assertIn("max_concurrency", data)
        self.assertIn("task_timeout", data)
        self.assertIn("default_target_branch", data)
        self.assertIn("anthropic_model", data)

    def test_patch_runtime_config_rejects_workspace_path_hot_update(self):
        response = self.client.patch(
            "/api/config/runtime",
            json={"worker_workspace_host_path": "/mnt/shared-workspaces"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("deployment-time", response.json()["detail"])

    def test_patch_runtime_config_rejects_invalid_max_concurrency(self):
        """PATCH /config/runtime should reject invalid max_concurrency."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"max_concurrency": 100},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("max_concurrency", response.json()["detail"].lower())

    def test_patch_runtime_config_rejects_invalid_task_timeout(self):
        """PATCH /config/runtime should reject invalid task_timeout."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"task_timeout": 30},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("task_timeout", response.json()["detail"].lower())

    def test_patch_runtime_config_rejects_invalid_url(self):
        """PATCH /config/runtime should reject invalid URL format."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"anthropic_base_url": "not-a-valid-url"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("url", response.json()["detail"].lower())

    def test_patch_runtime_config_rejects_empty_model(self):
        """PATCH /config/runtime should reject empty anthropic_model."""
        response = self.client.patch(
            "/api/config/runtime",
            json={"anthropic_model": "  "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("anthropic_model", response.json()["detail"].lower())

    def test_patch_runtime_config_null_worker_environment_variables_is_noop(self):
        """PATCH /config/runtime with null worker env vars should not replace rows."""
        with patch(
            "app.api.config_runtime.replace_worker_environment_variables",
            new=AsyncMock(),
        ) as mock_replace:
            response = self.client.patch(
                "/api/config/runtime",
                json={"worker_environment_variables": None},
            )

        self.assertEqual(response.status_code, 200)
        mock_replace.assert_not_awaited()

    def test_get_runtime_config_returns_worker_environment_variable_ids(self):
        """GET /config/runtime should expose persisted worker env var ids."""
        row = SimpleNamespace(
            id=7,
            key="SECRET_TOKEN",
            value="encrypted-value",
            is_secret=True,
        )

        with patch(
            "app.api.config_runtime.list_worker_environment_variables",
            new=AsyncMock(return_value=[row]),
        ):
            response = self.client.get("/api/config/runtime")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["worker_environment_variables"],
            [
                {
                    "id": 7,
                    "key": "SECRET_TOKEN",
                    "value": "",
                    "is_secret": True,
                    "value_configured": True,
                }
            ],
        )

    def test_patch_runtime_config_returns_500_for_unrelated_value_error(self):
        """PATCH /config/runtime should not report unrelated ValueErrors as 400."""
        with patch(
            "app.api.config_runtime.save_runtime_config_override",
            new=AsyncMock(side_effect=ValueError("unexpected failure")),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                "/api/config/runtime",
                json={"max_concurrency": 5},
            )
            client.close()

        self.assertEqual(response.status_code, 500)

    def test_patch_runtime_config_returns_reload_encryption_error_detail(self):
        """PATCH /config/runtime should surface reload encryption failures as 500s."""
        from app.core.config_crypto import ConfigEncryptionError

        with patch(
            "app.api.config_runtime.load_runtime_config_from_db",
            new=AsyncMock(side_effect=[None, ConfigEncryptionError("reload failed")]),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.patch(
                "/api/config/runtime",
                json={"max_concurrency": 5},
            )
            client.close()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "reload failed")

    def test_api_middleware_refreshes_runtime_config_for_non_auth_route(self):
        """API middleware syncs runtime config before non-authenticated routes run."""
        set_runtime_config({"oidc_enabled": False})

        mock_session = AsyncMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        async def refresh_side_effect(_session):
            set_runtime_config({"oidc_enabled": True})
            return True

        with patch("app.main.AsyncSessionLocal", return_value=mock_session_ctx):
            with patch(
                "app.main.refresh_runtime_config_if_stale",
                new=AsyncMock(side_effect=refresh_side_effect),
            ) as mock_refresh:
                original_db_override = app.dependency_overrides.pop(get_db, None)
                try:
                    with patch(
                        "app.api.auth.build_authorization_url",
                        new_callable=AsyncMock,
                        return_value="https://example.com/oauth/authorize",
                    ):
                        response = self.client.get("/api/auth/login", follow_redirects=False)
                finally:
                    if original_db_override is not None:
                        app.dependency_overrides[get_db] = original_db_override

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://example.com/oauth/authorize")
        mock_refresh.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
