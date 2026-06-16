#!/usr/bin/env python3
"""Unit tests for _validators.py — shared config validation utilities.

Covers:
- _is_valid_http_url helper
- _sanitize_string_list helper
- _validate_config_value for every config key section
- _normalize_updates with clear_oidc_client_secret flag
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException

from app.api._validators import (
    _is_valid_http_url,
    _normalize_updates,
    _sanitize_string_list,
    _validate_config_value,
)

# ---------------------------------------------------------------------------
# _is_valid_http_url
# ---------------------------------------------------------------------------


class IsValidHttpUrlTests(unittest.TestCase):
    """Tests for the _is_valid_http_url helper."""

    def test_valid_http_url(self):
        """Plain http URL should be valid."""
        self.assertTrue(_is_valid_http_url("http://example.com"))

    def test_valid_https_url(self):
        """HTTPS URL should be valid."""
        self.assertTrue(_is_valid_http_url("https://example.com"))

    def test_valid_https_url_with_path(self):
        """HTTPS URL with path should be valid."""
        self.assertTrue(_is_valid_http_url("https://example.com/api/v1"))

    def test_ftp_url_is_invalid(self):
        """FTP scheme should not be valid."""
        self.assertFalse(_is_valid_http_url("ftp://example.com"))

    def test_empty_string_is_invalid(self):
        """Empty string should not be valid."""
        self.assertFalse(_is_valid_http_url(""))

    def test_no_scheme_is_invalid(self):
        """URL without scheme should not be valid."""
        self.assertFalse(_is_valid_http_url("example.com"))

    def test_no_netloc_is_invalid(self):
        """URL with scheme but no netloc should not be valid."""
        self.assertFalse(_is_valid_http_url("http://"))


# ---------------------------------------------------------------------------
# _sanitize_string_list
# ---------------------------------------------------------------------------


class SanitizeStringListTests(unittest.TestCase):
    """Tests for the _sanitize_string_list helper."""

    def test_normal_comma_separated(self):
        """Normal comma-separated list should be preserved."""
        self.assertEqual(_sanitize_string_list("a,b,c"), "a,b,c")

    def test_whitespace_trimmed(self):
        """Whitespace around items should be stripped."""
        self.assertEqual(_sanitize_string_list(" a , b , c "), "a,b,c")

    def test_empty_items_removed(self):
        """Empty items from consecutive commas should be removed."""
        self.assertEqual(_sanitize_string_list("a,,b,,c"), "a,b,c")

    def test_all_empty(self):
        """String of only commas should result in empty string."""
        self.assertEqual(_sanitize_string_list(",,,"), "")

    def test_single_item(self):
        """Single item should be returned trimmed."""
        self.assertEqual(_sanitize_string_list(" admin "), "admin")

    def test_empty_string(self):
        """Empty input should return empty string."""
        self.assertEqual(_sanitize_string_list(""), "")


# ---------------------------------------------------------------------------
# _validate_config_value — max_concurrency
# ---------------------------------------------------------------------------


class ValidateMaxConcurrencyTests(unittest.TestCase):
    """Tests for max_concurrency config validation."""

    def test_valid_min_boundary(self):
        """min boundary (1) should be accepted."""
        self.assertEqual(_validate_config_value("max_concurrency", 1), 1)

    def test_valid_max_boundary(self):
        """max boundary (20) should be accepted."""
        self.assertEqual(_validate_config_value("max_concurrency", 20), 20)

    def test_valid_mid_range(self):
        """Mid-range value should be accepted."""
        self.assertEqual(_validate_config_value("max_concurrency", 10), 10)

    def test_invalid_zero(self):
        """Zero should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("max_concurrency", 0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_above_max(self):
        """Value above max should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("max_concurrency", 21)

    def test_invalid_negative(self):
        """Negative value should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("max_concurrency", -1)

    def test_invalid_non_int(self):
        """Non-integer type should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("max_concurrency", "5")


# ---------------------------------------------------------------------------
# _validate_config_value — task_timeout
# ---------------------------------------------------------------------------


class ValidateTaskTimeoutTests(unittest.TestCase):
    """Tests for task_timeout config validation."""

    def test_valid_min_boundary(self):
        """min boundary (60) should be accepted."""
        self.assertEqual(_validate_config_value("task_timeout", 60), 60)

    def test_valid_max_boundary(self):
        """max boundary (7200) should be accepted."""
        self.assertEqual(_validate_config_value("task_timeout", 7200), 7200)

    def test_invalid_below_min(self):
        """Below minimum should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("task_timeout", 59)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_above_max(self):
        """Above maximum should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("task_timeout", 7201)

    def test_invalid_float_type(self):
        """Float type should be rejected (must be int)."""
        with self.assertRaises(HTTPException):
            _validate_config_value("task_timeout", 60.0)


# ---------------------------------------------------------------------------
# _validate_config_value — scheduler_interval
# ---------------------------------------------------------------------------


class ValidateSchedulerIntervalTests(unittest.TestCase):
    """Tests for scheduler_interval config validation."""

    def test_valid_min_boundary(self):
        """min boundary (1) should be accepted."""
        self.assertEqual(_validate_config_value("scheduler_interval", 1), 1)

    def test_valid_max_boundary(self):
        """max boundary (60) should be accepted."""
        self.assertEqual(_validate_config_value("scheduler_interval", 60), 60)

    def test_invalid_zero(self):
        """Zero should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("scheduler_interval", 0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_above_max(self):
        """Above maximum should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("scheduler_interval", 61)


# ---------------------------------------------------------------------------
# _validate_config_value — default_target_branch
# ---------------------------------------------------------------------------


class ValidateDefaultTargetBranchTests(unittest.TestCase):
    """Tests for default_target_branch config validation."""

    def test_valid_branch_name(self):
        """Normal branch name should be accepted."""
        self.assertEqual(_validate_config_value("default_target_branch", "main"), "main")

    def test_valid_branch_with_whitespace_trimmed(self):
        """Whitespace should be stripped from branch name."""
        self.assertEqual(_validate_config_value("default_target_branch", " develop "), "develop")

    def test_invalid_empty_string(self):
        """Empty string should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("default_target_branch", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_whitespace_only(self):
        """Whitespace-only string should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("default_target_branch", "   ")

    def test_invalid_non_string(self):
        """Non-string type should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("default_target_branch", 123)


# ---------------------------------------------------------------------------
# _validate_config_value — anthropic_model (invalid paths)
# ---------------------------------------------------------------------------


class ValidateAnthropicModelTests(unittest.TestCase):
    """Tests for anthropic_model config validation (invalid paths)."""

    def test_valid_model_name(self):
        """Valid model name should be accepted."""
        self.assertEqual(_validate_config_value("anthropic_model", "claude-3"), "claude-3")

    def test_invalid_empty_string(self):
        """Empty string should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("anthropic_model", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_non_string(self):
        """Non-string type should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("anthropic_model", 42)

    def test_invalid_whitespace_only(self):
        """Whitespace-only string should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("anthropic_model", "   ")


# ---------------------------------------------------------------------------
# _validate_config_value — anthropic_api_key (invalid paths)
# ---------------------------------------------------------------------------


class ValidateAnthropicApiKeyTests(unittest.TestCase):
    """Tests for anthropic_api_key config validation (invalid paths)."""

    def test_valid_api_key(self):
        """Valid API key should be accepted."""
        self.assertEqual(_validate_config_value("anthropic_api_key", "sk-test-key"), "sk-test-key")

    def test_invalid_empty_string(self):
        """Empty string should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("anthropic_api_key", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_whitespace_only(self):
        """Whitespace-only string should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("anthropic_api_key", "   ")

    def test_invalid_non_string(self):
        """Non-string type should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("anthropic_api_key", 123)


# ---------------------------------------------------------------------------
# _validate_config_value — claude_max_turns
# ---------------------------------------------------------------------------


class ValidateClaudeMaxTurnsTests(unittest.TestCase):
    """Tests for claude_max_turns config validation."""

    def test_valid_min_boundary(self):
        """min boundary (1) should be accepted."""
        self.assertEqual(_validate_config_value("claude_max_turns", 1), 1)

    def test_valid_max_boundary(self):
        """max boundary (1000) should be accepted."""
        self.assertEqual(_validate_config_value("claude_max_turns", 1000), 1000)

    def test_valid_mid_range(self):
        """Mid-range value should be accepted."""
        self.assertEqual(_validate_config_value("claude_max_turns", 50), 50)

    def test_invalid_zero(self):
        """Zero should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("claude_max_turns", 0)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_above_max(self):
        """Above maximum should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("claude_max_turns", 1001)

    def test_invalid_non_int(self):
        """Non-integer type should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("claude_max_turns", "50")


# ---------------------------------------------------------------------------
# _validate_config_value — boolean fields
# ---------------------------------------------------------------------------


class ValidateBooleanFieldsTests(unittest.TestCase):
    """Tests for boolean config fields (alert_on_failure, allow_* flags)."""

    BOOLEAN_KEYS = [
        "alert_on_failure",
        "allow_monitor_for_users",
        "allow_schedule_overview_for_users",
        "allow_analytics_for_users",
        "allow_oidc_diagnostics_for_users",
    ]

    def test_valid_true(self):
        """True should be accepted for all boolean fields."""
        for key in self.BOOLEAN_KEYS:
            with self.subTest(key=key):
                self.assertTrue(_validate_config_value(key, True))

    def test_valid_false(self):
        """False should be accepted for all boolean fields."""
        for key in self.BOOLEAN_KEYS:
            with self.subTest(key=key):
                self.assertFalse(_validate_config_value(key, False))

    def test_invalid_string_true(self):
        """String 'true' should be rejected (must be actual bool)."""
        for key in self.BOOLEAN_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(HTTPException) as ctx:
                    _validate_config_value(key, "true")
                self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_int_not_accepted(self):
        """Integer 1 should be rejected (must be actual bool)."""
        for key in self.BOOLEAN_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(HTTPException):
                    _validate_config_value(key, 1)


# ---------------------------------------------------------------------------
# _validate_config_value — OIDC URL fields
# ---------------------------------------------------------------------------


class ValidateOidcUrlFieldsTests(unittest.TestCase):
    """Tests for OIDC URL config fields (oidc_issuer_url, oidc_redirect_uri)."""

    OIDC_URL_KEYS = ["oidc_issuer_url", "oidc_redirect_uri"]

    def test_valid_https_url(self):
        """HTTPS URLs should be accepted."""
        for key in self.OIDC_URL_KEYS:
            with self.subTest(key=key):
                result = _validate_config_value(key, "https://auth.example.com")
                self.assertEqual(result, "https://auth.example.com")

    def test_valid_http_url(self):
        """HTTP URLs (e.g. localhost) should be accepted."""
        for key in self.OIDC_URL_KEYS:
            with self.subTest(key=key):
                result = _validate_config_value(key, "http://localhost:8080")
                self.assertEqual(result, "http://localhost:8080")

    def test_valid_url_whitespace_trimmed(self):
        """Whitespace should be stripped from URL values."""
        for key in self.OIDC_URL_KEYS:
            with self.subTest(key=key):
                result = _validate_config_value(key, "  https://auth.example.com  ")
                self.assertEqual(result, "https://auth.example.com")

    def test_invalid_not_a_url(self):
        """Non-URL strings should be rejected."""
        for key in self.OIDC_URL_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(HTTPException) as ctx:
                    _validate_config_value(key, "not-a-url")
                self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_empty_string(self):
        """Empty string should be rejected."""
        for key in self.OIDC_URL_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(HTTPException):
                    _validate_config_value(key, "")

    def test_invalid_non_string(self):
        """Non-string type should be rejected."""
        for key in self.OIDC_URL_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(HTTPException):
                    _validate_config_value(key, 123)


# ---------------------------------------------------------------------------
# _validate_config_value — OIDC string fields
# ---------------------------------------------------------------------------


class ValidateOidcStringFieldsTests(unittest.TestCase):
    """Tests for OIDC string config fields (client_id, client_secret)."""

    def test_valid_client_id(self):
        """Valid oidc_client_id should be accepted and trimmed."""
        self.assertEqual(_validate_config_value("oidc_client_id", "my-client"), "my-client")

    def test_valid_client_id_trimmed(self):
        """Whitespace should be stripped from oidc_client_id."""
        self.assertEqual(_validate_config_value("oidc_client_id", "  my-client  "), "my-client")

    def test_invalid_empty_client_id(self):
        """Empty oidc_client_id should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("oidc_client_id", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_non_string_client_id(self):
        """Non-string oidc_client_id should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("oidc_client_id", 42)

    def test_valid_client_secret(self):
        """Valid oidc_client_secret should be accepted."""
        self.assertEqual(_validate_config_value("oidc_client_secret", "secret-val"), "secret-val")

    def test_invalid_empty_client_secret(self):
        """Empty oidc_client_secret should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("oidc_client_secret", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_whitespace_client_secret(self):
        """Whitespace-only oidc_client_secret should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("oidc_client_secret", "   ")


# ---------------------------------------------------------------------------
# _validate_config_value — session config fields
# ---------------------------------------------------------------------------


class ValidateSessionConfigTests(unittest.TestCase):
    """Tests for session-related config fields validation."""

    # --- session_cookie_name ---

    def test_valid_cookie_name(self):
        """Valid cookie name should be accepted."""
        self.assertEqual(_validate_config_value("session_cookie_name", "my_session"), "my_session")

    def test_valid_cookie_name_trimmed(self):
        """Whitespace should be stripped from cookie name."""
        self.assertEqual(_validate_config_value("session_cookie_name", "  sid  "), "sid")

    def test_invalid_empty_cookie_name(self):
        """Empty cookie name should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("session_cookie_name", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_cookie_name_with_spaces(self):
        """Cookie name containing spaces should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("session_cookie_name", "my session")

    def test_invalid_cookie_name_non_string(self):
        """Non-string cookie name should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("session_cookie_name", 123)

    # --- session_ttl_seconds ---

    def test_valid_session_ttl_min_boundary(self):
        """min boundary (300) should be accepted."""
        self.assertEqual(_validate_config_value("session_ttl_seconds", 300), 300)

    def test_valid_session_ttl_max_boundary(self):
        """max boundary (604800) should be accepted."""
        self.assertEqual(_validate_config_value("session_ttl_seconds", 604800), 604800)

    def test_invalid_session_ttl_below_min(self):
        """Below minimum should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("session_ttl_seconds", 299)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_session_ttl_above_max(self):
        """Above maximum should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("session_ttl_seconds", 604801)

    # --- cookie_secure ---

    def test_valid_cookie_secure_true(self):
        """True should be accepted."""
        self.assertTrue(_validate_config_value("cookie_secure", True))

    def test_valid_cookie_secure_false(self):
        """False should be accepted."""
        self.assertFalse(_validate_config_value("cookie_secure", False))

    def test_invalid_cookie_secure_non_bool(self):
        """Non-boolean should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("cookie_secure", "true")

    # --- cookie_samesite ---

    def test_valid_cookie_samesite_lax(self):
        """'lax' should be accepted."""
        self.assertEqual(_validate_config_value("cookie_samesite", "lax"), "lax")

    def test_valid_cookie_samesite_strict(self):
        """'strict' should be accepted."""
        self.assertEqual(_validate_config_value("cookie_samesite", "strict"), "strict")

    def test_valid_cookie_samesite_none(self):
        """'none' should be accepted."""
        self.assertEqual(_validate_config_value("cookie_samesite", "none"), "none")

    def test_valid_cookie_samesite_case_insensitive(self):
        """Value should be normalised to lowercase."""
        self.assertEqual(_validate_config_value("cookie_samesite", "Lax"), "lax")
        self.assertEqual(_validate_config_value("cookie_samesite", "STRICT"), "strict")

    def test_invalid_cookie_samesite_bad_value(self):
        """Invalid samesite value should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("cookie_samesite", "invalid")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_cookie_samesite_non_string(self):
        """Non-string should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("cookie_samesite", 1)


# ---------------------------------------------------------------------------
# _validate_config_value — auth admin fields
# ---------------------------------------------------------------------------


class ValidateAuthAdminFieldsTests(unittest.TestCase):
    """Tests for auth_admin_usernames and auth_admin_gitlab_groups."""

    def test_valid_admin_usernames(self):
        """Comma-separated usernames should be sanitized."""
        result = _validate_config_value("auth_admin_usernames", "admin, user1, user2")
        self.assertEqual(result, "admin,user1,user2")

    def test_valid_admin_gitlab_groups(self):
        """Comma-separated groups should be sanitized."""
        result = _validate_config_value("auth_admin_gitlab_groups", "group1 , group2")
        self.assertEqual(result, "group1,group2")

    def test_invalid_non_string_admin_usernames(self):
        """Non-string should be rejected."""
        with self.assertRaises(HTTPException) as ctx:
            _validate_config_value("auth_admin_usernames", 123)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_non_string_admin_groups(self):
        """Non-string (list) should be rejected."""
        with self.assertRaises(HTTPException):
            _validate_config_value("auth_admin_gitlab_groups", ["group1"])

    def test_empty_string_returns_empty(self):
        """Empty string should be accepted (sanitizes to empty)."""
        result = _validate_config_value("auth_admin_usernames", "")
        self.assertEqual(result, "")

    def test_whitespace_only_returns_empty(self):
        """Whitespace-only should be sanitized to empty."""
        result = _validate_config_value("auth_admin_gitlab_groups", "  ,  ,  ")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _validate_config_value — unknown key passthrough
# ---------------------------------------------------------------------------


class ValidateUnknownKeyTests(unittest.TestCase):
    """Tests for unknown config keys — should pass through unchanged."""

    def test_unknown_key_passes_through_string(self):
        """Unknown key with string value should pass through."""
        self.assertEqual(_validate_config_value("unknown_key", "any_value"), "any_value")

    def test_unknown_key_passes_through_int(self):
        """Unknown key with int value should pass through."""
        self.assertEqual(_validate_config_value("unknown_key", 42), 42)

    def test_unknown_key_passes_through_none(self):
        """Unknown key with None value should pass through."""
        self.assertIsNone(_validate_config_value("unknown_key", None))


# ---------------------------------------------------------------------------
# _normalize_updates — clear_oidc_client_secret
# ---------------------------------------------------------------------------


class NormalizeUpdatesOidcTests(unittest.TestCase):
    """Tests for _normalize_updates handling clear_oidc_client_secret."""

    def test_clear_oidc_client_secret_truthy(self):
        """Truthy value should be normalized to True."""
        result = _normalize_updates({"clear_oidc_client_secret": 1})
        self.assertEqual(result, {"clear_oidc_client_secret": True})

    def test_clear_oidc_client_secret_falsy(self):
        """Falsy value should be normalized to False."""
        result = _normalize_updates({"clear_oidc_client_secret": 0})
        self.assertEqual(result, {"clear_oidc_client_secret": False})

    def test_clear_oidc_with_other_flags(self):
        """clear_oidc_client_secret should coexist with other clear flags."""
        result = _normalize_updates({
            "clear_oidc_client_secret": True,
            "clear_alert_webhook_url": False,
        })
        self.assertIn("clear_oidc_client_secret", result)
        self.assertTrue(result["clear_oidc_client_secret"])
        self.assertIn("clear_alert_webhook_url", result)
        self.assertFalse(result["clear_alert_webhook_url"])

    def test_empty_updates_returns_empty(self):
        """Empty input should return empty dict."""
        result = _normalize_updates({})
        self.assertEqual(result, {})

    def test_non_clear_keys_are_ignored(self):
        """Keys that are not clear flags should not appear in output."""
        result = _normalize_updates({"some_random_key": "value", "max_concurrency": 5})
        self.assertEqual(result, {})

    def test_all_clear_flags_together(self):
        """All supported clear flags should be handled."""
        result = _normalize_updates({
            "clear_alert_webhook_url": 1,
            "clear_anthropic_api_key": 0,
            "clear_gitlab_bot_token": 1,
            "clear_gitlab_admin_token": 0,
            "clear_mattermost_bot_token": 0,
            "clear_oidc_client_secret": 1,
        })
        self.assertEqual(len(result), 6)
        self.assertTrue(result["clear_oidc_client_secret"])
        self.assertFalse(result["clear_anthropic_api_key"])


if __name__ == "__main__":
    unittest.main()
