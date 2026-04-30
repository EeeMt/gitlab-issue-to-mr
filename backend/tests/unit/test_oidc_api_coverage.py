"""Unit tests to increase coverage for backend/app/api/oidc.py from 71% → 85%+.

Coverage gaps addressed:
- _normalize_updates helper: None values (L41), invalid samesite (L44-45),
  empty strings (L46-47), valid passthrough (L48-49)
- _build_preview_settings helper: clear_* flag removal (L62)
- test_oidc_config endpoint auth branches: anonymous + OIDC-disabled (L182),
  skip-redirect header (L186-190), 401 without header (L191-193),
  OIDC/HTTP/encryption error handling (L211-212)
- get_oidc_diagnostics endpoint: full path (L234-327)
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from fastapi.testclient import TestClient

from app.main import app
from app.models import User
from app.database import get_db
from app.dependencies.auth import (
    require_admin_user,
    require_authenticated_context,
    require_authenticated_user,
)
from app.api.oidc import _normalize_updates, _build_preview_settings
from app.core.oidc import OIDCConfigurationError
from app.core.config_crypto import ConfigEncryptionError

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_admin_user():
    """Create a mock admin user that satisfies require_admin_user checks."""
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "admin"
    user.display_name = "Admin"
    user.email = "admin@test.com"
    user.platform_role = "platform_admin"
    user.auth_provider = "local"
    return user


def _make_settings(**overrides):
    """Build a SimpleNamespace with every attribute the OIDC endpoints read."""
    defaults = dict(
        oidc_enabled=True,
        oidc_issuer_url="https://idp.example.com",
        oidc_client_id="test-client",
        oidc_client_secret="test-secret",
        oidc_redirect_uri="https://app.example.com/api/auth/callback",
        session_cookie_name="codify_session",
        session_ttl_seconds=28800,
        cookie_secure=True,
        cookie_samesite="lax",
        break_glass_enabled=True,
        admin_gitlab_groups=set(),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


DISCOVERY = {
    "issuer": "https://idp.example.com",
    "authorization_endpoint": "https://idp.example.com/oauth/authorize",
    "token_endpoint": "https://idp.example.com/oauth/token",
    "userinfo_endpoint": "https://idp.example.com/userinfo",
}

AUTH_URL = "https://idp.example.com/oauth/authorize?client_id=test"


# ===================================================================
# 1. _normalize_updates  (lines 41, 44-49)
# ===================================================================


class TestNormalizeUpdates(unittest.TestCase):
    """Cover every branch in _normalize_updates."""

    def test_none_values_are_skipped(self):
        """Line 41: continue when value is None."""
        result = _normalize_updates({"oidc_issuer_url": None, "oidc_client_id": "x"})
        self.assertNotIn("oidc_issuer_url", result)
        self.assertEqual(result["oidc_client_id"], "x")

    def test_all_none_returns_empty(self):
        """Line 41: all-None dict produces empty output."""
        result = _normalize_updates({"a": None, "b": None})
        self.assertEqual(result, {})

    def test_session_ttl_clamped_to_minimum(self):
        """Line 43: values below 300 are raised to 300."""
        self.assertEqual(
            _normalize_updates({"session_ttl_seconds": 10})["session_ttl_seconds"],
            300,
        )

    def test_session_ttl_clamped_to_maximum(self):
        """Line 43: values above 604800 are lowered."""
        self.assertEqual(
            _normalize_updates({"session_ttl_seconds": 999999})["session_ttl_seconds"],
            604800,
        )

    def test_session_ttl_within_range_unchanged(self):
        """Line 43: values within 300..604800 pass through unchanged."""
        self.assertEqual(
            _normalize_updates({"session_ttl_seconds": 3600})["session_ttl_seconds"],
            3600,
        )

    def test_invalid_cookie_samesite_skipped(self):
        """Lines 44-45: unrecognised samesite value is dropped."""
        result = _normalize_updates({"cookie_samesite": "bogus"})
        self.assertNotIn("cookie_samesite", result)

    def test_valid_cookie_samesite_lax(self):
        """Lines 48-49: 'lax' is accepted."""
        self.assertEqual(
            _normalize_updates({"cookie_samesite": "lax"})["cookie_samesite"], "lax"
        )

    def test_valid_cookie_samesite_strict(self):
        """Lines 48-49: 'strict' is accepted."""
        self.assertEqual(
            _normalize_updates({"cookie_samesite": "strict"})["cookie_samesite"],
            "strict",
        )

    def test_valid_cookie_samesite_none(self):
        """Lines 48-49: 'none' is accepted."""
        self.assertEqual(
            _normalize_updates({"cookie_samesite": "none"})["cookie_samesite"], "none"
        )

    def test_empty_string_skipped(self):
        """Lines 46-47: empty string is dropped."""
        result = _normalize_updates({"oidc_issuer_url": ""})
        self.assertNotIn("oidc_issuer_url", result)

    def test_whitespace_only_string_skipped(self):
        """Lines 46-47: whitespace-only string is dropped."""
        result = _normalize_updates({"oidc_client_id": "   "})
        self.assertNotIn("oidc_client_id", result)

    def test_valid_string_passes_through(self):
        """Lines 48-49: non-empty string is kept."""
        result = _normalize_updates({"oidc_issuer_url": "https://x.com"})
        self.assertEqual(result["oidc_issuer_url"], "https://x.com")

    def test_boolean_values_pass_through(self):
        """Lines 48-49: booleans hit the else branch and are kept."""
        result = _normalize_updates({"oidc_enabled": True, "cookie_secure": False})
        self.assertTrue(result["oidc_enabled"])
        self.assertFalse(result["cookie_secure"])

    def test_mixed_input_filters_correctly(self):
        """Integration: several branches exercised together."""
        result = _normalize_updates({
            "a_none_key": None,
            "cookie_samesite": "bad",
            "oidc_issuer_url": "  ",
            "oidc_client_id": "good-value",
            "session_ttl_seconds": 100,
            "cookie_secure": True,
        })
        self.assertNotIn("a_none_key", result)
        self.assertNotIn("cookie_samesite", result)
        self.assertNotIn("oidc_issuer_url", result)
        self.assertEqual(result["oidc_client_id"], "good-value")
        self.assertEqual(result["session_ttl_seconds"], 300)
        self.assertTrue(result["cookie_secure"])


# ===================================================================
# 2. _build_preview_settings  (line 62)
# ===================================================================


class TestBuildPreviewSettings(unittest.TestCase):
    """Cover clear_* flag removal in _build_preview_settings."""

    @patch("app.config.get_settings")
    @patch("app.api.oidc.Settings")
    def test_clear_flags_are_removed(self, MockSettings, mock_get_settings):
        """Line 62: keys starting with 'clear_' are deleted before Settings()."""
        base = MagicMock()
        base.model_dump.return_value = {
            "oidc_enabled": False,
            "secret_key": "k",
        }
        mock_get_settings.return_value = base
        MockSettings.return_value = MagicMock()

        _build_preview_settings({
            "oidc_issuer_url": "https://new.example.com",
            "clear_oidc_client_secret": True,
        })

        call_kwargs = MockSettings.call_args[1]
        self.assertNotIn("clear_oidc_client_secret", call_kwargs)
        self.assertEqual(call_kwargs["oidc_issuer_url"], "https://new.example.com")

    @patch("app.config.get_settings")
    @patch("app.api.oidc.Settings")
    def test_multiple_clear_flags_all_removed(self, MockSettings, mock_get_settings):
        """Line 62: multiple clear_* keys are all stripped."""
        base = MagicMock()
        base.model_dump.return_value = {"oidc_enabled": True}
        mock_get_settings.return_value = base
        MockSettings.return_value = MagicMock()

        _build_preview_settings({
            "clear_oidc_client_secret": True,
            "clear_something_else": True,
        })

        call_kwargs = MockSettings.call_args[1]
        clear_keys = [k for k in call_kwargs if k.startswith("clear_")]
        self.assertEqual(clear_keys, [])

    @patch("app.config.get_settings")
    @patch("app.api.oidc.Settings")
    def test_non_clear_flags_preserved(self, MockSettings, mock_get_settings):
        """Line 62: normal updates survive the clear-flag pass."""
        base = MagicMock()
        base.model_dump.return_value = {"oidc_enabled": False}
        mock_get_settings.return_value = base
        MockSettings.return_value = MagicMock()

        _build_preview_settings({"oidc_enabled": True})

        call_kwargs = MockSettings.call_args[1]
        self.assertTrue(call_kwargs["oidc_enabled"])


# ===================================================================
# 3. POST /config/oidc/test – auth branches  (lines 182, 186-193, 211-212)
# ===================================================================


class TestOIDCConfigTestAuthBranches(unittest.TestCase):
    """Cover the custom auth logic inside the test_oidc_config endpoint.

    The OIDC router is registered with a router-level
    ``dependencies=[Depends(require_authenticated_user)]``.
    We override that (returning None) so the request reaches the endpoint body,
    then override ``require_admin_user`` separately to control ``current_user``.
    """

    def setUp(self):
        self.client = TestClient(app)
        self.mock_db = AsyncMock()
        self.mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalars=MagicMock(all=MagicMock(return_value=[]))
            )
        )
        app.dependency_overrides[get_db] = lambda: self.mock_db
        # Bypass router-level auth so the request reaches the endpoint body
        app.dependency_overrides[require_authenticated_user] = lambda: None

    def tearDown(self):
        app.dependency_overrides.clear()

    # -- helpers ---------------------------------------------------------

    def _post_oidc_test(self, headers=None):
        """POST /api/config/oidc/test with minimal valid body."""
        return self.client.post(
            "/api/config/oidc/test",
            json={"auth": {}},
            headers=headers or {},
        )

    # -- Line 182: anonymous + OIDC disabled => allowed ------------------

    def test_anonymous_allowed_when_oidc_disabled(self):
        """Line 182: when oidc_enabled=False and current_user=None, request passes."""
        app.dependency_overrides[require_admin_user] = lambda: None
        settings = _make_settings(oidc_enabled=False)

        with patch("app.api.oidc.get_effective_settings", return_value=settings), \
             patch("app.api.oidc.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch("app.api.oidc._build_preview_settings", return_value=settings), \
             patch("app.api.oidc.get_oidc_discovery_document_for_settings",
                   new_callable=AsyncMock, return_value=DISCOVERY), \
             patch("app.api.oidc.build_authorization_url_for_settings",
                   new_callable=AsyncMock, return_value=AUTH_URL):

            resp = self._post_oidc_test()
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["issuer"], "https://idp.example.com")

    # -- Lines 186-190: skip-redirect header => allowed ------------------

    def test_skip_redirect_header_allows_when_oidc_enabled(self):
        """Lines 186-190: X-Skip-Auth-Redirect=true bypasses 401."""
        app.dependency_overrides[require_admin_user] = lambda: None
        settings = _make_settings(oidc_enabled=True)

        with patch("app.api.oidc.get_effective_settings", return_value=settings), \
             patch("app.api.oidc.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch("app.api.oidc._build_preview_settings", return_value=settings), \
             patch("app.api.oidc.get_oidc_discovery_document_for_settings",
                   new_callable=AsyncMock, return_value=DISCOVERY), \
             patch("app.api.oidc.build_authorization_url_for_settings",
                   new_callable=AsyncMock, return_value=AUTH_URL):

            resp = self._post_oidc_test(
                headers={"X-Skip-Auth-Redirect": "true"}
            )
            self.assertEqual(resp.status_code, 200)

    # -- Lines 191-193: no skip header => 401 ---------------------------

    def test_401_when_oidc_enabled_no_user_no_skip_header(self):
        """Lines 191-193: raises 401 if OIDC enabled, user=None, no header."""
        app.dependency_overrides[require_admin_user] = lambda: None
        settings = _make_settings(oidc_enabled=True)

        with patch("app.api.oidc.get_effective_settings", return_value=settings):
            resp = self._post_oidc_test()
            self.assertEqual(resp.status_code, 401)
            self.assertIn("Authentication required", resp.json()["detail"])

    # -- Lines 211-212: OIDCConfigurationError => 400 --------------------

    def test_oidc_configuration_error_returns_400(self):
        """Lines 211-212: OIDCConfigurationError is mapped to HTTP 400."""
        app.dependency_overrides[require_admin_user] = lambda: None
        settings = _make_settings(oidc_enabled=False)

        with patch("app.api.oidc.get_effective_settings", return_value=settings), \
             patch("app.api.oidc.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch("app.api.oidc._build_preview_settings", return_value=settings), \
             patch("app.api.oidc.get_oidc_discovery_document_for_settings",
                   new_callable=AsyncMock,
                   side_effect=OIDCConfigurationError("bad issuer")):

            resp = self._post_oidc_test()
            self.assertEqual(resp.status_code, 400)
            self.assertIn("bad issuer", resp.json()["detail"])

    # -- Lines 211-212: ConfigEncryptionError => 400 ---------------------

    def test_config_encryption_error_returns_400(self):
        """Lines 211-212: ConfigEncryptionError is mapped to HTTP 400."""
        app.dependency_overrides[require_admin_user] = lambda: None
        settings = _make_settings(oidc_enabled=False)

        with patch("app.api.oidc.get_effective_settings", return_value=settings), \
             patch("app.api.oidc.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch("app.api.oidc._build_preview_settings", return_value=settings), \
             patch("app.api.oidc.get_oidc_discovery_document_for_settings",
                   new_callable=AsyncMock,
                   side_effect=ConfigEncryptionError("decrypt failed")):

            resp = self._post_oidc_test()
            self.assertEqual(resp.status_code, 400)
            self.assertIn("decrypt failed", resp.json()["detail"])

    # -- Lines 211-212: httpx.HTTPError => 400 ---------------------------

    def test_httpx_error_returns_400(self):
        """Lines 211-212: httpx transport error is mapped to HTTP 400."""
        app.dependency_overrides[require_admin_user] = lambda: None
        settings = _make_settings(oidc_enabled=False)

        with patch("app.api.oidc.get_effective_settings", return_value=settings), \
             patch("app.api.oidc.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch("app.api.oidc._build_preview_settings", return_value=settings), \
             patch("app.api.oidc.get_oidc_discovery_document_for_settings",
                   new_callable=AsyncMock,
                   side_effect=httpx.ConnectError("connection refused")):

            resp = self._post_oidc_test()
            self.assertEqual(resp.status_code, 400)


# ===================================================================
# 4. GET /config/oidc/diagnostics  (lines 234-327)
# ===================================================================


class TestOIDCDiagnosticsEndpoint(unittest.TestCase):
    """Cover the full get_oidc_diagnostics endpoint."""

    def setUp(self):
        self.client = TestClient(app)

        # Mock database
        self.mock_db = AsyncMock()
        self.mock_db.execute = AsyncMock(
            return_value=MagicMock(
                scalars=MagicMock(all=MagicMock(return_value=[]))
            )
        )
        app.dependency_overrides[get_db] = lambda: self.mock_db

        # Provide admin auth context so require_page_access passes
        admin = _make_admin_user()

        async def _auth_ctx(request=None, db=None):
            return SimpleNamespace(user=admin, session=None, failure_detail=None)

        app.dependency_overrides[require_authenticated_context] = _auth_ctx

    def tearDown(self):
        app.dependency_overrides.clear()

    # -- helper ----------------------------------------------------------

    def _get(self, settings=None, discovery=None, discovery_side_effect=None,
             auth_url=None, auth_url_side_effect=None):
        """GET /api/config/oidc/diagnostics with standard mocks."""
        settings = settings or _make_settings()
        discovery = discovery or DISCOVERY
        auth_url = auth_url or AUTH_URL

        with patch("app.api.oidc.load_runtime_config_from_db", new_callable=AsyncMock), \
             patch("app.api.oidc.get_effective_settings", return_value=settings), \
             patch("app.api.oidc.get_oidc_discovery_document_for_settings",
                   new_callable=AsyncMock,
                   return_value=discovery,
                   side_effect=discovery_side_effect), \
             patch("app.api.oidc.build_authorization_url_for_settings",
                   new_callable=AsyncMock,
                   return_value=auth_url,
                   side_effect=auth_url_side_effect):

            return self.client.get("/api/config/oidc/diagnostics")

    # -- Happy path (lines 234-327 main flow) ----------------------------

    def test_happy_path_returns_full_diagnostics(self):
        """Lines 244-258, 278-286, 297-316, 318-323, 327-347: success."""
        resp = self._get()
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        # Top-level fields
        self.assertTrue(data["oidc_enabled"])
        self.assertEqual(data["issuer_url"], "https://idp.example.com")
        self.assertTrue(data["client_id_configured"])
        self.assertTrue(data["client_secret_configured"])
        self.assertEqual(data["session_cookie_name"], "codify_session")
        self.assertEqual(data["session_ttl_seconds"], 28800)
        self.assertTrue(data["cookie_secure"])
        self.assertEqual(data["cookie_samesite"], "lax")

        # Discovery-derived fields
        self.assertEqual(data["discovery_issuer"], "https://idp.example.com")
        self.assertEqual(
            data["authorization_endpoint"],
            "https://idp.example.com/oauth/authorize",
        )
        self.assertEqual(
            data["token_endpoint"], "https://idp.example.com/oauth/token"
        )
        self.assertEqual(
            data["userinfo_endpoint"], "https://idp.example.com/userinfo"
        )
        self.assertEqual(data["authorization_url_preview"], AUTH_URL)

        # Checks
        check_keys = [c["key"] for c in data["checks"]]
        self.assertIn("discovery", check_keys)
        self.assertIn("authorization_endpoint", check_keys)
        self.assertIn("token_endpoint", check_keys)
        self.assertIn("userinfo_endpoint", check_keys)
        self.assertIn("redirect_uri", check_keys)
        self.assertIn("scope", check_keys)
        self.assertIn("cookie_policy", check_keys)

        disco = next(c for c in data["checks"] if c["key"] == "discovery")
        self.assertEqual(disco["status"], "ok")

    # -- Discovery: OIDCConfigurationError (lines 259-267) ---------------

    def test_oidc_config_error_in_discovery(self):
        """Lines 259-267: OIDCConfigurationError → discovery check is error."""
        resp = self._get(
            discovery_side_effect=OIDCConfigurationError("issuer missing"),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        disco = next(c for c in data["checks"] if c["key"] == "discovery")
        self.assertEqual(disco["status"], "error")
        self.assertIn("issuer missing", disco["detail"])

        # Discovery-derived fields should be None
        self.assertIsNone(data["discovery_issuer"])
        self.assertIsNone(data["authorization_endpoint"])
        self.assertIsNone(data["token_endpoint"])
        self.assertIsNone(data["userinfo_endpoint"])

    # -- Discovery: httpx.HTTPError (lines 268-276) ----------------------

    def test_http_error_in_discovery(self):
        """Lines 268-276: httpx.HTTPError → discovery check is error."""
        resp = self._get(
            discovery_side_effect=httpx.ConnectError("connection refused"),
        )
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        disco = next(c for c in data["checks"] if c["key"] == "discovery")
        self.assertEqual(disco["status"], "error")
        self.assertIn("Failed to fetch", disco["detail"])

    # -- Redirect URI: valid + ends with /api/auth/callback (lines 278-286)

    def test_valid_redirect_uri_with_correct_path_is_ok(self):
        """Lines 278-286: valid URL ending with /api/auth/callback → status ok."""
        resp = self._get()
        data = resp.json()
        uri_check = next(c for c in data["checks"] if c["key"] == "redirect_uri")
        self.assertEqual(uri_check["status"], "ok")
        self.assertEqual(
            uri_check["detail"],
            "https://app.example.com/api/auth/callback",
        )

    # -- Redirect URI: valid but wrong path → warning --------------------

    def test_valid_redirect_uri_wrong_path_is_warning(self):
        """Lines 278-286: valid URL with wrong path → status warning."""
        settings = _make_settings(
            oidc_redirect_uri="https://app.example.com/wrong/path"
        )
        resp = self._get(settings=settings)
        data = resp.json()
        uri_check = next(c for c in data["checks"] if c["key"] == "redirect_uri")
        self.assertEqual(uri_check["status"], "warning")

    # -- Redirect URI: invalid (lines 287-295) ---------------------------

    def test_invalid_redirect_uri_is_error(self):
        """Lines 287-295: non-URL redirect URI → error check."""
        settings = _make_settings(oidc_redirect_uri="not-a-valid-url")
        resp = self._get(settings=settings)
        data = resp.json()
        uri_check = next(c for c in data["checks"] if c["key"] == "redirect_uri")
        self.assertEqual(uri_check["status"], "error")
        self.assertIn("missing or invalid", uri_check["detail"])

    def test_empty_redirect_uri_is_error(self):
        """Lines 287-295: empty redirect URI → error check."""
        settings = _make_settings(oidc_redirect_uri="")
        resp = self._get(settings=settings)
        data = resp.json()
        uri_check = next(c for c in data["checks"] if c["key"] == "redirect_uri")
        self.assertEqual(uri_check["status"], "error")

    # -- Scope check always present (lines 297-304) ----------------------

    def test_scope_check_present_and_ok(self):
        """Lines 297-304: scope check is always status ok."""
        resp = self._get()
        data = resp.json()
        scope = next(c for c in data["checks"] if c["key"] == "scope")
        self.assertEqual(scope["status"], "ok")
        self.assertIn("openid", scope["detail"])

    # -- Cookie policy check (lines 305-316) -----------------------------

    def test_cookie_policy_ok_when_no_warnings(self):
        """Lines 305-316: no warnings → cookie_policy is ok."""
        resp = self._get()
        data = resp.json()
        cookie = next(c for c in data["checks"] if c["key"] == "cookie_policy")
        self.assertEqual(cookie["status"], "ok")
        self.assertIn("secure=True", cookie["detail"])

    def test_cookie_policy_warning_when_warnings_exist(self):
        """Lines 305-316: warnings present → cookie_policy is warning."""
        settings = _make_settings(session_ttl_seconds=90000)
        resp = self._get(settings=settings)
        data = resp.json()
        cookie = next(c for c in data["checks"] if c["key"] == "cookie_policy")
        self.assertEqual(cookie["status"], "warning")

    # -- Authorization URL preview failure (lines 324-325) ---------------

    def test_auth_url_preview_none_on_error(self):
        """Lines 324-325: build_authorization_url raises → preview is None."""
        resp = self._get(
            auth_url_side_effect=OIDCConfigurationError("cannot build"),
        )
        data = resp.json()
        self.assertIsNone(data["authorization_url_preview"])

    def test_auth_url_preview_none_on_http_error(self):
        """Lines 324-325: httpx error during auth URL → preview is None."""
        resp = self._get(
            auth_url_side_effect=httpx.ConnectError("timeout"),
        )
        data = resp.json()
        self.assertIsNone(data["authorization_url_preview"])

    # -- Additional field checks -----------------------------------------

    def test_client_secret_not_configured(self):
        """client_secret_configured is False when secret is empty."""
        settings = _make_settings(oidc_client_secret="")
        resp = self._get(settings=settings)
        data = resp.json()
        self.assertFalse(data["client_secret_configured"])

    def test_client_id_not_configured(self):
        """client_id_configured is False when client_id is empty."""
        settings = _make_settings(oidc_client_id="")
        resp = self._get(settings=settings)
        data = resp.json()
        self.assertFalse(data["client_id_configured"])

    def test_break_glass_reflected(self):
        """break_glass_enabled is reflected from settings."""
        settings = _make_settings(break_glass_enabled=False)
        resp = self._get(settings=settings)
        data = resp.json()
        self.assertFalse(data["break_glass_enabled"])

    def test_warnings_surface_in_response(self):
        """Warnings from _build_oidc_diagnostics_warnings appear in response."""
        settings = _make_settings(
            session_ttl_seconds=90000,
        )
        resp = self._get(settings=settings)
        data = resp.json()
        self.assertTrue(len(data["warnings"]) > 0)
        self.assertTrue(
            any("24 hours" in w for w in data["warnings"]),
            "Expected a long-TTL warning",
        )

    def test_required_scopes_in_response(self):
        """required_scopes and required_scope_string are populated."""
        resp = self._get()
        data = resp.json()
        self.assertIn("openid", data["required_scopes"])
        self.assertIn("openid", data["required_scope_string"])

    def test_oidc_disabled_reflected(self):
        """oidc_enabled=False is reflected in the response."""
        settings = _make_settings(oidc_enabled=False)
        resp = self._get(settings=settings)
        data = resp.json()
        self.assertFalse(data["oidc_enabled"])


if __name__ == "__main__":
    unittest.main()
