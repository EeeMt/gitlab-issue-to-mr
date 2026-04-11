"""Coverage tests for config_runtime.py and config_integration.py.

Targets uncovered lines:
  config_runtime.py  – 113, 137, 145, 152-157, 160-165, 168-173, 181,
                       191-222, 265, 267, 275-276, 279-280, 283-284, 296-305
  config_integration.py – 75, 93-95, 101-107, 120-146, 161-164
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.config import get_settings, reset_runtime_config

# ── Lazy env setup so Settings() can be constructed ─────────────────
_ORIG_ENC_KEY = os.environ.get("CONFIG_ENCRYPTION_KEY")


def _ensure_env():
    os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-config-key")
    get_settings.cache_clear()
    reset_runtime_config()


def _restore_env():
    reset_runtime_config()
    if _ORIG_ENC_KEY is None:
        os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
    else:
        os.environ["CONFIG_ENCRYPTION_KEY"] = _ORIG_ENC_KEY
    get_settings.cache_clear()


# ── Helper: mock user ───────────────────────────────────────────────

# ── Helper: mock db ─────────────────────────────────────────────────
def _make_mock_db():
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=None)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.delete = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db, mock_result


def _make_test_client():
    from types import SimpleNamespace

    from app.database import get_db
    from app.dependencies.auth import require_authenticated_context
    from app.main import app

    mock_db, mock_result = _make_mock_db()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    # Override the auth context that require_admin_user depends on
    async def mock_auth_context(request=None, auth_context=None):
        return SimpleNamespace(
            user=SimpleNamespace(
                id=1, username="admin", platform_role="platform_admin"
            ),
            session=None,
            gitlab_access_token=None,
            gitlab_refresh_token=None,
        )

    app.dependency_overrides[require_authenticated_context] = mock_auth_context

    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    return client, app, mock_db


# =====================================================================
# Part 1 – config_runtime.py  _validate_config_value direct tests
# =====================================================================


class ValidateConfigValueTests(unittest.TestCase):
    """Direct tests for _validate_config_value() in config_runtime.py.

    Covers lines 113, 137, 145, 152-157, 160-165, 168-173, 181, 191-222.
    """

    def setUp(self):
        _ensure_env()

    def tearDown(self):
        _restore_env()

    @staticmethod
    def _call(key, value):
        from app.api.config_runtime import _validate_config_value
        return _validate_config_value(key, value)

    # ── _build_preview_settings – clear_* flags (line 113) ──────────

    def test_build_preview_settings_removes_clear_flags(self):
        """_build_preview_settings strips clear_* keys (line 113)."""
        from app.api.config_runtime import _build_preview_settings

        base = get_settings()
        result = _build_preview_settings(
            {"max_concurrency": 5, "clear_alert_webhook_url": True}, base
        )
        self.assertEqual(result.max_concurrency, 5)
        # clear_* key should not leak through
        self.assertFalse(hasattr(result, "clear_alert_webhook_url"))

    # ── scheduler_interval validation (line 137) ────────────────────

    def test_scheduler_interval_valid(self):
        """scheduler_interval accepted when in range 1-60 (line 137)."""
        result = self._call("scheduler_interval", 30)
        self.assertEqual(result, 30)

    def test_scheduler_interval_too_low(self):
        """scheduler_interval rejected when < 1 (line 137)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("scheduler_interval", 0)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("scheduler_interval", ctx.exception.detail)

    def test_scheduler_interval_too_high(self):
        """scheduler_interval rejected when > 60 (line 137)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("scheduler_interval", 61)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_scheduler_interval_wrong_type(self):
        """scheduler_interval rejected when not int (line 137)."""
        with self.assertRaises(HTTPException):
            self._call("scheduler_interval", "fast")

    # ── default_target_branch validation (line 145) ─────────────────

    def test_default_target_branch_valid(self):
        """Non-empty string accepted and stripped (line 145)."""
        result = self._call("default_target_branch", "  develop  ")
        self.assertEqual(result, "develop")

    def test_default_target_branch_empty(self):
        """Empty string rejected (line 145)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("default_target_branch", "   ")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("default_target_branch", ctx.exception.detail)

    def test_default_target_branch_wrong_type(self):
        """Non-string rejected (line 145)."""
        with self.assertRaises(HTTPException):
            self._call("default_target_branch", 123)

    # ── max_retries validation (lines 152-157) ──────────────────────

    def test_max_retries_valid_zero(self):
        """max_retries=0 is accepted (line 152)."""
        self.assertEqual(self._call("max_retries", 0), 0)

    def test_max_retries_valid_upper_bound(self):
        """max_retries=10 is accepted (line 152)."""
        self.assertEqual(self._call("max_retries", 10), 10)

    def test_max_retries_too_high(self):
        """max_retries > 10 rejected (lines 152-157)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("max_retries", 11)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("max_retries", ctx.exception.detail)

    def test_max_retries_negative(self):
        """max_retries < 0 rejected (lines 152-157)."""
        with self.assertRaises(HTTPException):
            self._call("max_retries", -1)

    def test_max_retries_wrong_type(self):
        """Non-int rejected (lines 152-157)."""
        with self.assertRaises(HTTPException):
            self._call("max_retries", "five")

    # ── retry_delay validation (lines 160-165) ──────────────────────

    def test_retry_delay_valid(self):
        """retry_delay in range 1-3600 accepted (line 160)."""
        self.assertEqual(self._call("retry_delay", 60), 60)

    def test_retry_delay_too_low(self):
        """retry_delay < 1 rejected (lines 160-165)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("retry_delay", 0)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("retry_delay", ctx.exception.detail)

    def test_retry_delay_too_high(self):
        """retry_delay > 3600 rejected (lines 160-165)."""
        with self.assertRaises(HTTPException):
            self._call("retry_delay", 3601)

    def test_retry_delay_wrong_type(self):
        """Non-int rejected (lines 160-165)."""
        with self.assertRaises(HTTPException):
            self._call("retry_delay", 3.14)

    # ── slot_max_tasks validation (lines 168-173) ───────────────────

    def test_slot_max_tasks_valid(self):
        """slot_max_tasks in range 0-100 accepted (line 168)."""
        self.assertEqual(self._call("slot_max_tasks", 50), 50)

    def test_slot_max_tasks_zero(self):
        """slot_max_tasks=0 accepted (line 168)."""
        self.assertEqual(self._call("slot_max_tasks", 0), 0)

    def test_slot_max_tasks_too_high(self):
        """slot_max_tasks > 100 rejected (lines 168-173)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("slot_max_tasks", 101)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("slot_max_tasks", ctx.exception.detail)

    def test_slot_max_tasks_negative(self):
        """slot_max_tasks < 0 rejected (lines 168-173)."""
        with self.assertRaises(HTTPException):
            self._call("slot_max_tasks", -1)

    def test_slot_max_tasks_wrong_type(self):
        """Non-int rejected (lines 168-173)."""
        with self.assertRaises(HTTPException):
            self._call("slot_max_tasks", "many")

    # ── URL fields – strip + return (line 181) ──────────────────────

    def test_anthropic_base_url_strips_whitespace(self):
        """Valid URL is stripped and returned (line 181)."""
        result = self._call("anthropic_base_url", "  https://api.example.com  ")
        self.assertEqual(result, "https://api.example.com")

    def test_alert_webhook_url_valid(self):
        """alert_webhook_url accepts a valid http URL (line 181)."""
        result = self._call("alert_webhook_url", "http://hooks.example.com/alert")
        self.assertEqual(result, "http://hooks.example.com/alert")

    # ── anthropic_api_key validation (lines 191-197) ────────────────

    def test_anthropic_api_key_valid(self):
        """Non-empty string accepted and stripped (line 191)."""
        result = self._call("anthropic_api_key", "  sk-ant-key  ")
        self.assertEqual(result, "sk-ant-key")

    def test_anthropic_api_key_empty(self):
        """Empty/whitespace-only rejected (lines 191-197)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("anthropic_api_key", "   ")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("anthropic_api_key", ctx.exception.detail)

    def test_anthropic_api_key_wrong_type(self):
        """Non-string rejected (lines 191-197)."""
        with self.assertRaises(HTTPException):
            self._call("anthropic_api_key", 12345)

    # ── claude_max_turns validation (lines 199-205) ─────────────────

    def test_claude_max_turns_valid(self):
        """claude_max_turns in range 1-1000 accepted (line 199)."""
        self.assertEqual(self._call("claude_max_turns", 100), 100)

    def test_claude_max_turns_too_low(self):
        """claude_max_turns < 1 rejected (lines 199-205)."""
        with self.assertRaises(HTTPException) as ctx:
            self._call("claude_max_turns", 0)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("claude_max_turns", ctx.exception.detail)

    def test_claude_max_turns_too_high(self):
        """claude_max_turns > 1000 rejected (lines 199-205)."""
        with self.assertRaises(HTTPException):
            self._call("claude_max_turns", 1001)

    def test_claude_max_turns_wrong_type(self):
        """Non-int rejected (lines 199-205)."""
        with self.assertRaises(HTTPException):
            self._call("claude_max_turns", "ten")

    # ── boolean fields validation (lines 207-220) ───────────────────

    def test_boolean_field_alert_on_failure(self):
        """alert_on_failure accepted when bool (lines 207-220)."""
        self.assertEqual(self._call("alert_on_failure", True), True)
        self.assertEqual(self._call("alert_on_failure", False), False)

    def test_boolean_field_allow_monitor_for_users(self):
        """allow_monitor_for_users accepted when bool (lines 207-220)."""
        self.assertTrue(self._call("allow_monitor_for_users", True))

    def test_boolean_field_allow_schedule_overview(self):
        """allow_schedule_overview_for_users accepted when bool (lines 207-220)."""
        self.assertFalse(self._call("allow_schedule_overview_for_users", False))

    def test_boolean_field_allow_analytics(self):
        """allow_analytics_for_users accepted when bool (lines 207-220)."""
        self.assertTrue(self._call("allow_analytics_for_users", True))

    def test_boolean_field_allow_oidc_diagnostics(self):
        """allow_oidc_diagnostics_for_users accepted when bool (lines 207-220)."""
        self.assertTrue(self._call("allow_oidc_diagnostics_for_users", True))

    def test_boolean_field_slot_max_tasks_enforce(self):
        """slot_max_tasks_enforce accepted when bool (lines 207-220)."""
        self.assertFalse(self._call("slot_max_tasks_enforce", False))

    def test_boolean_field_rejects_non_bool(self):
        """Boolean fields reject non-bool values (lines 215-219)."""
        for field in (
            "alert_on_failure",
            "allow_monitor_for_users",
            "allow_schedule_overview_for_users",
            "allow_analytics_for_users",
            "allow_oidc_diagnostics_for_users",
            "slot_max_tasks_enforce",
        ):
            with self.assertRaises(HTTPException, msg=f"{field} should reject str"):
                self._call(field, "yes")

    # ── unknown key passthrough (line 222) ──────────────────────────

    def test_unknown_key_passthrough(self):
        """Unknown keys are returned as-is without validation (line 222)."""
        self.assertEqual(self._call("unknown_future_key", 42), 42)


# =====================================================================
# Part 2 – config_runtime.py endpoint tests (clear flags, reset key)
# =====================================================================


class RuntimeEndpointCoverageTests(unittest.TestCase):
    """Endpoint tests for update_runtime_config (clear flags) and
    reset_runtime_config_key.

    Covers lines 265, 267, 275-276, 279-280, 283-284, 296-305.
    """

    def setUp(self):
        _ensure_env()
        self.client, self.app, self.mock_db = _make_test_client()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        _restore_env()

    # ── PATCH with clear_alert_webhook_url (lines 264-276) ──────────

    @patch("app.api.config_runtime.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_runtime.get_effective_settings")
    @patch("app.api.config_runtime.get_settings")
    @patch("app.api.config_runtime.save_runtime_config_override", new_callable=AsyncMock)
    @patch("app.api.config_runtime.reset_runtime_config_override", new_callable=AsyncMock)
    def test_patch_clear_alert_webhook_url(
        self,
        mock_reset,
        mock_save,
        mock_get_settings,
        mock_eff_settings,
        mock_load,
    ):
        """PATCH with clear_alert_webhook_url adds the current webhook to runtime_updates
        and calls save_runtime_config_override with it (line 265)."""
        mock_settings = MagicMock()
        mock_settings.alert_webhook_url = "https://old-webhook.example.com"
        mock_settings.anthropic_api_key = ""
        mock_settings.model_dump.return_value = get_settings().model_dump()
        mock_get_settings.return_value = mock_settings
        mock_eff_settings.return_value = get_settings()

        response = self.client.patch(
            "/api/config/runtime",
            json={"clear_alert_webhook_url": True},
        )

        self.assertEqual(response.status_code, 200)
        # Line 265: runtime_updates["alert_webhook_url"] = get_settings().alert_webhook_url
        # Then it's saved via save_runtime_config_override in the for-loop
        mock_save.assert_awaited()
        save_calls = [c.args for c in mock_save.await_args_list]
        # The save should include alert_webhook_url with the old value
        saved_keys = [c[1] for c in save_calls]
        self.assertIn("alert_webhook_url", saved_keys)

    @patch("app.api.config_runtime.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_runtime.get_effective_settings")
    @patch("app.api.config_runtime.get_settings")
    @patch("app.api.config_runtime.save_runtime_config_override", new_callable=AsyncMock)
    @patch("app.api.config_runtime.reset_runtime_config_override", new_callable=AsyncMock)
    def test_patch_clear_anthropic_api_key(
        self,
        mock_reset,
        mock_save,
        mock_get_settings,
        mock_eff_settings,
        mock_load,
    ):
        """PATCH with clear_anthropic_api_key adds the current key to runtime_updates
        and calls save_runtime_config_override with it (line 267)."""
        mock_settings = MagicMock()
        mock_settings.alert_webhook_url = ""
        mock_settings.anthropic_api_key = "sk-old-key"
        mock_settings.model_dump.return_value = get_settings().model_dump()
        mock_get_settings.return_value = mock_settings
        mock_eff_settings.return_value = get_settings()

        response = self.client.patch(
            "/api/config/runtime",
            json={"clear_anthropic_api_key": True},
        )

        self.assertEqual(response.status_code, 200)
        # Line 267: runtime_updates["anthropic_api_key"] = get_settings().anthropic_api_key
        mock_save.assert_awaited()
        save_calls = [c.args for c in mock_save.await_args_list]
        saved_keys = [c[1] for c in save_calls]
        self.assertIn("anthropic_api_key", saved_keys)

    # ── PATCH with ConfigEncryptionError (lines 283-284) ────────────

    @patch("app.api.config_runtime.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_runtime.get_effective_settings")
    @patch("app.api.config_runtime.get_settings")
    @patch(
        "app.api.config_runtime.save_runtime_config_override",
        new_callable=AsyncMock,
        side_effect=__import__(
            "app.core.config_crypto", fromlist=["ConfigEncryptionError"]
        ).ConfigEncryptionError("encryption failed"),
    )
    def test_patch_config_encryption_error_returns_500(
        self, mock_save, mock_get_settings, mock_eff_settings, mock_load
    ):
        """ConfigEncryptionError during save returns 500 (lines 283-284)."""
        mock_settings = MagicMock()
        mock_settings.alert_webhook_url = ""
        mock_settings.anthropic_api_key = ""
        mock_settings.model_dump.return_value = get_settings().model_dump()
        mock_get_settings.return_value = mock_settings
        mock_eff_settings.return_value = get_settings()

        response = self.client.patch(
            "/api/config/runtime",
            json={"max_concurrency": 3},
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("encryption failed", response.json()["detail"])

    # ── DELETE /config/runtime/{key} (lines 296-305) ────────────────

    @patch("app.api.config_runtime.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_runtime.get_effective_settings")
    @patch("app.api.config_runtime.reset_runtime_config_override", new_callable=AsyncMock)
    @patch(
        "app.api.config_runtime.get_runtime_config_types",
        return_value={"max_concurrency": int, "task_timeout": int},
    )
    def test_delete_runtime_key_success(
        self, mock_types, mock_reset, mock_eff_settings, mock_load
    ):
        """DELETE /config/runtime/max_concurrency resets the key (lines 296-305)."""
        mock_eff_settings.return_value = get_settings()

        response = self.client.delete("/api/config/runtime/max_concurrency")

        self.assertEqual(response.status_code, 200)
        mock_reset.assert_awaited_once()

    @patch(
        "app.api.config_runtime.get_runtime_config_types",
        return_value={"max_concurrency": int},
    )
    def test_delete_runtime_key_unknown_returns_404(self, mock_types):
        """DELETE /config/runtime/{unknown} returns 404 (lines 296-300)."""
        response = self.client.delete("/api/config/runtime/nonexistent_key")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown config key", response.json()["detail"])


# =====================================================================
# Part 3 – config_integration.py coverage
# =====================================================================


class IntegrationConfigHelperTests(unittest.TestCase):
    """Direct tests for helper functions in config_integration.py.

    Covers lines 75, 93-95, 101-107.
    """

    def setUp(self):
        _ensure_env()

    def tearDown(self):
        _restore_env()

    # ── _build_preview_settings_with_integration (line 75) ──────────

    def test_build_preview_strips_clear_flags(self):
        """_build_preview_settings_with_integration removes clear_* keys (line 75)."""
        from app.api.config_integration import _build_preview_settings_with_integration

        base = get_settings()
        result = _build_preview_settings_with_integration(
            {"gitlab_url": "https://gitlab.new.com", "clear_gitlab_bot_token": True},
            base,
        )
        self.assertEqual(result.gitlab_url, "https://gitlab.new.com")

    # ── _normalize_integration_updates (lines 93-95) ────────────────

    def test_normalize_strips_and_accepts_valid_token(self):
        """gitlab_bot_token is stripped and accepted (lines 93-95)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_bot_token": "  my-token  "}
        )
        self.assertEqual(result["gitlab_bot_token"], "my-token")

    def test_normalize_strips_admin_token(self):
        """gitlab_admin_token is stripped and accepted (lines 93-95)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_admin_token": " admin-tok "}
        )
        self.assertEqual(result["gitlab_admin_token"], "admin-tok")

    def test_normalize_strips_webhook_secret(self):
        """gitlab_webhook_secret is stripped and accepted (lines 93-95)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_webhook_secret": " secret123 "}
        )
        self.assertEqual(result["gitlab_webhook_secret"], "secret123")

    def test_normalize_rejects_empty_token(self):
        """Empty token strings are omitted (lines 93-95)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_bot_token": "   "}
        )
        self.assertNotIn("gitlab_bot_token", result)

    def test_normalize_rejects_non_string_token(self):
        """Non-string token values are omitted (lines 93-95)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_bot_token": 12345}
        )
        self.assertNotIn("gitlab_bot_token", result)

    def test_normalize_invalid_gitlab_url_omitted(self):
        """Invalid gitlab_url is silently omitted (line 92)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_url": "not-a-url"}
        )
        self.assertNotIn("gitlab_url", result)

    def test_normalize_valid_gitlab_url_stripped(self):
        """Valid gitlab_url is stripped and accepted (line 92)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {"gitlab_url": "  https://gitlab.example.com  "}
        )
        self.assertEqual(result["gitlab_url"], "https://gitlab.example.com")

    def test_normalize_clear_flags_preserved(self):
        """clear_* flags are normalised to bool (line 88)."""
        from app.api.config_integration import _normalize_integration_updates

        result = _normalize_integration_updates(
            {
                "clear_gitlab_bot_token": 1,
                "clear_gitlab_admin_token": 0,
                "clear_gitlab_webhook_secret": True,
            }
        )
        self.assertTrue(result["clear_gitlab_bot_token"])
        self.assertFalse(result["clear_gitlab_admin_token"])
        self.assertTrue(result["clear_gitlab_webhook_secret"])

    # ── _validate_gitlab_integration (lines 101-107) ────────────────

    def test_validate_gitlab_integration_rejects_empty_url(self):
        """Empty gitlab_url raises 400 (lines 101-105)."""
        from app.api.config_integration import _validate_gitlab_integration

        mock_settings = SimpleNamespace(
            gitlab_url="   ", gitlab_bot_token="valid-token"
        )
        with self.assertRaises(HTTPException) as ctx:
            _validate_gitlab_integration(mock_settings)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("gitlab_url", ctx.exception.detail)

    def test_validate_gitlab_integration_rejects_empty_token(self):
        """Empty gitlab_bot_token raises 400 (lines 106-110)."""
        from app.api.config_integration import _validate_gitlab_integration

        mock_settings = SimpleNamespace(
            gitlab_url="https://gitlab.example.com", gitlab_bot_token="   "
        )
        with self.assertRaises(HTTPException) as ctx:
            _validate_gitlab_integration(mock_settings)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("gitlab_bot_token", ctx.exception.detail)

    def test_validate_gitlab_integration_passes_when_both_set(self):
        """Validation passes when both url and token are present."""
        from app.api.config_integration import _validate_gitlab_integration

        mock_settings = SimpleNamespace(
            gitlab_url="https://gitlab.example.com", gitlab_bot_token="glpat-xyz"
        )
        # Should not raise
        _validate_gitlab_integration(mock_settings)


# =====================================================================
# Part 4 – config_integration.py endpoint tests
# =====================================================================


class IntegrationEndpointCoverageTests(unittest.TestCase):
    """Endpoint tests for test_gitlab_config and invalidate_project_cache.

    Covers lines 120-146, 161-164.
    """

    def setUp(self):
        _ensure_env()
        self.client, self.app, self.mock_db = _make_test_client()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        _restore_env()

    # ── POST /config/gitlab/test – success (lines 120-150) ──────────

    @patch("app.api.config_integration.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_integration.get_effective_settings")
    @patch("app.api.config_integration.GitLabClient")
    def test_test_gitlab_config_success(
        self, mock_gl_cls, mock_eff_settings, mock_load
    ):
        """POST /config/gitlab/test returns version and username on success (lines 120-150)."""
        # Settings must have non-empty gitlab_url and gitlab_bot_token to pass validation
        mock_settings = MagicMock()
        mock_settings.gitlab_url = "https://gitlab.example.com"
        mock_settings.gitlab_bot_token = "glpat-validtoken"
        mock_settings.gitlab_admin_token = ""
        mock_settings.gitlab_webhook_secret = ""
        settings_dump = get_settings().model_dump()
        settings_dump.update({
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_bot_token": "glpat-validtoken",
        })
        mock_settings.model_dump.return_value = settings_dump
        mock_eff_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.gl.http_get.side_effect = [
            {"version": "16.5.0"},
            {"username": "bot-user"},
        ]
        mock_client.close = MagicMock()
        mock_gl_cls.return_value = mock_client

        response = self.client.post(
            "/api/config/gitlab/test",
            json={"integration": {"gitlab_url": "https://gitlab.example.com"}},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["server_version"], "16.5.0")
        self.assertEqual(data["username"], "bot-user")
        mock_client.close.assert_called_once()

    # ── POST /config/gitlab/test – GitLab error (lines 138-142) ─────

    @patch("app.api.config_integration.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_integration.get_effective_settings")
    @patch("app.api.config_integration.GitLabClient")
    def test_test_gitlab_config_gitlab_error(
        self, mock_gl_cls, mock_eff_settings, mock_load
    ):
        """POST /config/gitlab/test returns 400 on GitLab error (lines 138-142)."""
        mock_settings = MagicMock()
        mock_settings.gitlab_url = "https://gitlab.example.com"
        mock_settings.gitlab_bot_token = "glpat-validtoken"
        mock_settings.gitlab_admin_token = ""
        mock_settings.gitlab_webhook_secret = ""
        settings_dump = get_settings().model_dump()
        settings_dump.update({
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_bot_token": "glpat-validtoken",
        })
        mock_settings.model_dump.return_value = settings_dump
        mock_eff_settings.return_value = mock_settings

        from gitlab.exceptions import GitlabError

        mock_client = MagicMock()
        mock_client.gl.http_get.side_effect = GitlabError("connection refused")
        mock_client.close = MagicMock()
        mock_gl_cls.return_value = mock_client

        response = self.client.post(
            "/api/config/gitlab/test",
            json={"integration": {"gitlab_url": "https://gitlab.example.com"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("GitLab config test failed", response.json()["detail"])
        mock_client.close.assert_called_once()

    # ── POST /config/gitlab/test – httpx error (lines 138-142) ──────

    @patch("app.api.config_integration.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_integration.get_effective_settings")
    @patch("app.api.config_integration.GitLabClient")
    def test_test_gitlab_config_httpx_error(
        self, mock_gl_cls, mock_eff_settings, mock_load
    ):
        """POST /config/gitlab/test returns 400 on httpx error (lines 138-142)."""
        import httpx

        mock_settings = MagicMock()
        mock_settings.gitlab_url = "https://gitlab.example.com"
        mock_settings.gitlab_bot_token = "glpat-validtoken"
        mock_settings.gitlab_admin_token = ""
        mock_settings.gitlab_webhook_secret = ""
        settings_dump = get_settings().model_dump()
        settings_dump.update({
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_bot_token": "glpat-validtoken",
        })
        mock_settings.model_dump.return_value = settings_dump
        mock_eff_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.gl.http_get.side_effect = httpx.ConnectError("timeout")
        mock_client.close = MagicMock()
        mock_gl_cls.return_value = mock_client

        response = self.client.post(
            "/api/config/gitlab/test",
            json={"integration": {}},
        )

        self.assertEqual(response.status_code, 400)
        mock_client.close.assert_called_once()

    # ── POST /config/gitlab/test – validation failure (lines 101-110)

    @patch("app.api.config_integration.load_runtime_config_from_db", new_callable=AsyncMock)
    @patch("app.api.config_integration.get_effective_settings")
    def test_test_gitlab_config_validation_failure(
        self, mock_eff_settings, mock_load
    ):
        """POST /config/gitlab/test returns 400 when url/token empty (lines 101-110)."""
        # Create a settings-like object with empty URL
        mock_settings = MagicMock()
        mock_settings.gitlab_url = "   "
        mock_settings.gitlab_bot_token = "valid"
        mock_settings.model_dump.return_value = {
            **get_settings().model_dump(),
            "gitlab_url": "   ",
        }
        mock_eff_settings.return_value = mock_settings

        response = self.client.post(
            "/api/config/gitlab/test",
            json={"integration": {}},
        )

        self.assertEqual(response.status_code, 400)

    # ── POST /config/gitlab/projects/cache/invalidate (lines 161-164)

    @patch("app.core.gitlab_client.invalidate_project_list_cache")
    def test_invalidate_project_cache_success(self, mock_invalidate):
        """POST invalidate returns success message (lines 161-164)."""
        response = self.client.post(
            "/api/config/gitlab/projects/cache/invalidate"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("invalidated", data["message"].lower())
        mock_invalidate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
