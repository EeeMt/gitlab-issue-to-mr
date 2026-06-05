#!/usr/bin/env python3
"""Unit tests for backend/app/core/oidc.py — covering all public functions.

Targets the missed lines: 42-47, 52-72, 77, 82-91, 96, 101-119,
124-141, 146-153, 158-175.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import app.core.oidc as oidc_mod
from app.core.oidc import (
    OIDCConfigurationError,
    build_authorization_url,
    build_authorization_url_for_settings,
    ensure_oidc_configured,
    exchange_code_for_tokens,
    exchange_refresh_token,
    fetch_userinfo,
    get_oidc_discovery_document,
    get_oidc_discovery_document_for_settings,
    get_required_oidc_scope_string,
    get_required_oidc_scopes,
    validate_id_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_ISSUER = "https://gitlab.example.com"

FAKE_DISCOVERY = {
    "issuer": FAKE_ISSUER,
    "authorization_endpoint": f"{FAKE_ISSUER}/oauth/authorize",
    "token_endpoint": f"{FAKE_ISSUER}/oauth/token",
    "userinfo_endpoint": f"{FAKE_ISSUER}/oauth/userinfo",
    "jwks_uri": f"{FAKE_ISSUER}/oauth/discovery/keys",
}


def _make_settings(**overrides) -> SimpleNamespace:
    """Return a minimal Settings-like object with OIDC fields populated."""
    defaults = {
        "oidc_enabled": True,
        "oidc_issuer_url": FAKE_ISSUER,
        "oidc_client_id": "my-client-id",
        "oidc_client_secret": "my-client-secret",
        "oidc_redirect_uri": "https://app.example.com/api/auth/callback",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_httpx_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Response that behaves like a successful response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} Error", request=MagicMock(), response=resp,
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _make_async_client(response: MagicMock) -> MagicMock:
    """Return a mock httpx.AsyncClient context manager."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ===================================================================
# ensure_oidc_configured  (lines 42-47)
# ===================================================================
class TestEnsureOIDCConfigured(unittest.TestCase):
    """Tests for the synchronous ensure_oidc_configured validator."""

    def test_raises_when_oidc_disabled(self):
        """Line 42-43: OIDC disabled with require_enabled=True raises."""
        settings = _make_settings(oidc_enabled=False)
        with self.assertRaises(OIDCConfigurationError) as ctx:
            ensure_oidc_configured(settings)
        self.assertIn("disabled", str(ctx.exception))

    def test_does_not_raise_when_require_enabled_false(self):
        """Line 42 branch: require_enabled=False skips the enabled check."""
        settings = _make_settings(oidc_enabled=False)
        # Should NOT raise even though oidc_enabled is False
        ensure_oidc_configured(settings, require_enabled=False)

    def test_raises_when_issuer_url_missing(self):
        """Line 44-45: Missing issuer URL raises OIDCConfigurationError."""
        settings = _make_settings(oidc_issuer_url="")
        with self.assertRaises(OIDCConfigurationError) as ctx:
            ensure_oidc_configured(settings)
        self.assertIn("incomplete", str(ctx.exception))

    def test_raises_when_client_id_missing(self):
        """Line 44-45: Missing client ID raises OIDCConfigurationError."""
        settings = _make_settings(oidc_client_id="")
        with self.assertRaises(OIDCConfigurationError) as ctx:
            ensure_oidc_configured(settings)
        self.assertIn("incomplete", str(ctx.exception))

    def test_raises_when_redirect_uri_missing(self):
        """Line 44-45: Missing redirect URI raises OIDCConfigurationError."""
        settings = _make_settings(oidc_redirect_uri="")
        with self.assertRaises(OIDCConfigurationError) as ctx:
            ensure_oidc_configured(settings)
        self.assertIn("incomplete", str(ctx.exception))

    def test_raises_when_client_secret_missing(self):
        """Line 46-47: Missing client secret raises when required."""
        settings = _make_settings(oidc_client_secret="")
        with self.assertRaises(OIDCConfigurationError) as ctx:
            ensure_oidc_configured(settings)
        self.assertIn("secret", str(ctx.exception).lower())

    def test_does_not_raise_when_require_client_secret_false(self):
        """Line 46 branch: require_client_secret=False skips secret check."""
        settings = _make_settings(oidc_client_secret="")
        ensure_oidc_configured(settings, require_client_secret=False)

    def test_passes_when_fully_configured(self):
        """Happy path: all settings present, no exception raised."""
        settings = _make_settings()
        ensure_oidc_configured(settings)  # should not raise


# ===================================================================
# get_oidc_discovery_document_for_settings  (lines 52-72)
# ===================================================================
class TestGetOIDCDiscoveryDocumentForSettings(unittest.IsolatedAsyncioTestCase):
    """Tests for async discovery document fetching and caching."""

    def setUp(self):
        """Reset the module-level discovery cache before each test."""
        oidc_mod._discovery_cache["issuer"] = ""
        oidc_mod._discovery_cache["expires_at"] = 0.0
        oidc_mod._discovery_cache["document"] = None

    def tearDown(self):
        """Reset the module-level discovery cache after each test."""
        oidc_mod._discovery_cache["issuer"] = ""
        oidc_mod._discovery_cache["expires_at"] = 0.0
        oidc_mod._discovery_cache["document"] = None

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_fetches_discovery_document_from_remote(self, _mock_ssl):
        """Lines 63-72: Fetches discovery via HTTP and populates cache."""
        settings = _make_settings()
        resp = _make_httpx_response(FAKE_DISCOVERY)
        mock_client = _make_async_client(resp)

        with patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client):
            doc = await get_oidc_discovery_document_for_settings(settings)

        self.assertEqual(doc, FAKE_DISCOVERY)
        mock_client.get.assert_awaited_once()
        # Verify cache was populated
        self.assertEqual(oidc_mod._discovery_cache["issuer"], FAKE_ISSUER)
        self.assertIsNotNone(oidc_mod._discovery_cache["document"])

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_returns_cached_document_when_valid(self, _mock_ssl):
        """Lines 56-61: Returns cached doc if issuer matches and not expired."""
        import time

        settings = _make_settings()
        # Pre-populate the cache with a valid entry
        oidc_mod._discovery_cache["issuer"] = FAKE_ISSUER
        oidc_mod._discovery_cache["document"] = FAKE_DISCOVERY
        oidc_mod._discovery_cache["expires_at"] = time.time() + 600

        # Should NOT make any HTTP call
        with patch("app.core.oidc.httpx.AsyncClient") as mock_httpx:
            doc = await get_oidc_discovery_document_for_settings(settings)

        self.assertEqual(doc, FAKE_DISCOVERY)
        mock_httpx.assert_not_called()

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_refreshes_cache_when_expired(self, _mock_ssl):
        """Lines 59: Expired cache triggers a new fetch."""
        settings = _make_settings()
        # Pre-populate with an expired entry
        oidc_mod._discovery_cache["issuer"] = FAKE_ISSUER
        oidc_mod._discovery_cache["document"] = {"old": True}
        oidc_mod._discovery_cache["expires_at"] = 0.0  # expired

        resp = _make_httpx_response(FAKE_DISCOVERY)
        mock_client = _make_async_client(resp)

        with patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client):
            doc = await get_oidc_discovery_document_for_settings(settings)

        self.assertEqual(doc, FAKE_DISCOVERY)
        mock_client.get.assert_awaited_once()

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_refreshes_cache_when_issuer_changes(self, _mock_ssl):
        """Line 58: Different issuer invalidates cache."""
        import time

        settings = _make_settings()
        # Cache has a different issuer
        oidc_mod._discovery_cache["issuer"] = "https://other.example.com"
        oidc_mod._discovery_cache["document"] = {"old": True}
        oidc_mod._discovery_cache["expires_at"] = time.time() + 600

        resp = _make_httpx_response(FAKE_DISCOVERY)
        mock_client = _make_async_client(resp)

        with patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client):
            doc = await get_oidc_discovery_document_for_settings(settings)

        self.assertEqual(doc, FAKE_DISCOVERY)
        mock_client.get.assert_awaited_once()

    async def test_raises_when_config_incomplete(self):
        """Line 52: Delegates to ensure_oidc_configured which raises."""
        settings = _make_settings(oidc_issuer_url="")
        with self.assertRaises(OIDCConfigurationError):
            await get_oidc_discovery_document_for_settings(settings)

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_strips_trailing_slash_from_issuer(self, _mock_ssl):
        """Line 55: Trailing slash on issuer URL is stripped."""
        settings = _make_settings(oidc_issuer_url=f"{FAKE_ISSUER}/")
        resp = _make_httpx_response(FAKE_DISCOVERY)
        mock_client = _make_async_client(resp)

        with patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client):
            await get_oidc_discovery_document_for_settings(settings)

        # Verify the discovery URL was built without double slash
        call_args = mock_client.get.call_args
        called_url = call_args[0][0]
        self.assertEqual(called_url, f"{FAKE_ISSUER}/.well-known/openid-configuration")
        self.assertEqual(oidc_mod._discovery_cache["issuer"], FAKE_ISSUER)


# ===================================================================
# get_oidc_discovery_document  (line 77)
# ===================================================================
class TestGetOIDCDiscoveryDocument(unittest.IsolatedAsyncioTestCase):
    """Tests for the convenience wrapper that uses effective settings."""

    async def test_delegates_to_for_settings_variant(self):
        """Line 77: Calls get_oidc_discovery_document_for_settings with effective settings."""
        fake_settings = _make_settings()
        with (
            patch(
                "app.core.oidc.get_effective_settings", return_value=fake_settings
            ) as mock_get,
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ) as mock_fetch,
        ):
            result = await get_oidc_discovery_document()

        mock_get.assert_called_once()
        mock_fetch.assert_awaited_once_with(fake_settings)
        self.assertEqual(result, FAKE_DISCOVERY)


# ===================================================================
# build_authorization_url_for_settings  (lines 82-91)
# ===================================================================
class TestBuildAuthorizationUrlForSettings(unittest.IsolatedAsyncioTestCase):
    """Tests for building the OIDC authorization redirect URL."""

    async def test_builds_correct_url_with_all_params(self):
        """Lines 82-91: URL contains all required OAuth2 params."""
        settings = _make_settings()
        with patch(
            "app.core.oidc.get_oidc_discovery_document_for_settings",
            new_callable=AsyncMock,
            return_value=FAKE_DISCOVERY,
        ):
            url = await build_authorization_url_for_settings(
                settings, state="test-state", nonce="test-nonce"
            )

        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(parsed.path.endswith("/oauth/authorize"))

        params = parse_qs(parsed.query)
        self.assertEqual(params["client_id"], [settings.oidc_client_id])
        self.assertEqual(params["redirect_uri"], [settings.oidc_redirect_uri])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["state"], ["test-state"])
        self.assertEqual(params["nonce"], ["test-nonce"])
        self.assertIn("openid", params["scope"][0])


# ===================================================================
# build_authorization_url  (line 96)
# ===================================================================
class TestBuildAuthorizationUrl(unittest.IsolatedAsyncioTestCase):
    """Tests for the convenience wrapper using effective settings."""

    async def test_delegates_to_for_settings_variant(self):
        """Line 96: Calls build_authorization_url_for_settings with effective settings."""
        fake_settings = _make_settings()
        expected_url = "https://gitlab.example.com/oauth/authorize?foo=bar"
        with (
            patch(
                "app.core.oidc.get_effective_settings", return_value=fake_settings
            ),
            patch(
                "app.core.oidc.build_authorization_url_for_settings",
                new_callable=AsyncMock,
                return_value=expected_url,
            ) as mock_build,
        ):
            result = await build_authorization_url("s", "n")

        mock_build.assert_awaited_once_with(fake_settings, "s", "n")
        self.assertEqual(result, expected_url)


# ===================================================================
# exchange_code_for_tokens  (lines 101-119)
# ===================================================================
class TestExchangeCodeForTokens(unittest.IsolatedAsyncioTestCase):
    """Tests for the authorization-code → token exchange."""

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_posts_correct_payload_and_returns_tokens(self, _mock_ssl):
        """Lines 101-119: Sends correct form payload and returns parsed JSON."""
        fake_settings = _make_settings()
        token_response = {
            "access_token": "at-123",
            "id_token": "idt-456",
            "refresh_token": "rt-789",
            "token_type": "Bearer",
        }
        resp = _make_httpx_response(token_response)
        mock_client = _make_async_client(resp)

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await exchange_code_for_tokens("auth-code-xyz")

        self.assertEqual(result, token_response)

        # Verify the POST payload
        call_kwargs = mock_client.post.call_args
        posted_url = call_kwargs[0][0]
        self.assertEqual(posted_url, FAKE_DISCOVERY["token_endpoint"])

        posted_data = call_kwargs[1]["data"]
        self.assertEqual(posted_data["grant_type"], "authorization_code")
        self.assertEqual(posted_data["code"], "auth-code-xyz")
        self.assertEqual(posted_data["redirect_uri"], fake_settings.oidc_redirect_uri)
        self.assertEqual(posted_data["client_id"], fake_settings.oidc_client_id)
        self.assertEqual(posted_data["client_secret"], fake_settings.oidc_client_secret)

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_raises_when_config_incomplete(self, _mock_ssl):
        """Line 102: ensure_oidc_configured raises before HTTP call."""
        fake_settings = _make_settings(oidc_client_secret="")
        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
        ):
            with self.assertRaises(OIDCConfigurationError):
                await exchange_code_for_tokens("code")


# ===================================================================
# exchange_refresh_token  (lines 124-141)
# ===================================================================
class TestExchangeRefreshToken(unittest.IsolatedAsyncioTestCase):
    """Tests for the refresh-token exchange flow."""

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_posts_correct_payload_and_returns_tokens(self, _mock_ssl):
        """Lines 124-141: Sends refresh_token grant and returns new tokens."""
        fake_settings = _make_settings()
        token_response = {
            "access_token": "new-at-123",
            "refresh_token": "new-rt-456",
            "token_type": "Bearer",
        }
        resp = _make_httpx_response(token_response)
        mock_client = _make_async_client(resp)

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await exchange_refresh_token("old-refresh-token")

        self.assertEqual(result, token_response)

        # Verify the POST payload
        call_kwargs = mock_client.post.call_args
        posted_url = call_kwargs[0][0]
        self.assertEqual(posted_url, FAKE_DISCOVERY["token_endpoint"])

        posted_data = call_kwargs[1]["data"]
        self.assertEqual(posted_data["grant_type"], "refresh_token")
        self.assertEqual(posted_data["refresh_token"], "old-refresh-token")
        self.assertEqual(posted_data["client_id"], fake_settings.oidc_client_id)
        self.assertEqual(posted_data["client_secret"], fake_settings.oidc_client_secret)

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_raises_when_config_incomplete(self, _mock_ssl):
        """Line 125: ensure_oidc_configured raises before HTTP call."""
        fake_settings = _make_settings(oidc_issuer_url="")
        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
        ):
            with self.assertRaises(OIDCConfigurationError):
                await exchange_refresh_token("token")


# ===================================================================
# fetch_userinfo  (lines 146-153)
# ===================================================================
class TestFetchUserinfo(unittest.IsolatedAsyncioTestCase):
    """Tests for fetching the authenticated user's profile."""

    @patch("app.core.oidc.get_ssl_verify", return_value=True)
    async def test_sends_bearer_token_and_returns_userinfo(self, _mock_ssl):
        """Lines 146-153: GET request with Bearer token returns user info."""
        userinfo = {
            "sub": "42",
            "name": "Alice",
            "email": "alice@example.com",
            "preferred_username": "alice",
        }
        resp = _make_httpx_response(userinfo)
        mock_client = _make_async_client(resp)

        with (
            patch(
                "app.core.oidc.get_effective_settings",
                return_value=_make_settings(),
            ),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await fetch_userinfo("my-access-token")

        self.assertEqual(result, userinfo)

        # Verify Authorization header was sent
        call_kwargs = mock_client.get.call_args
        called_url = call_kwargs[0][0]
        self.assertEqual(called_url, FAKE_DISCOVERY["userinfo_endpoint"])
        headers = call_kwargs[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer my-access-token")


# ===================================================================
# validate_id_token  (lines 158-175)
# ===================================================================
class TestValidateIdToken(unittest.IsolatedAsyncioTestCase):
    """Tests for ID token (JWT) validation."""

    async def test_returns_claims_when_nonce_matches(self):
        """Lines 158-175: Successful decode + nonce check returns claims."""
        fake_settings = _make_settings()
        expected_claims = {
            "sub": "42",
            "aud": fake_settings.oidc_client_id,
            "iss": FAKE_ISSUER,
            "nonce": "correct-nonce",
        }

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwk_client = MagicMock()
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.PyJWKClient", return_value=mock_jwk_client),
            patch("app.core.oidc.jwt.decode", return_value=expected_claims),
        ):
            result = await validate_id_token("fake.jwt.token", "correct-nonce")

        self.assertEqual(result, expected_claims)

    async def test_raises_on_nonce_mismatch(self):
        """Lines 173-174: Mismatched nonce raises InvalidTokenError."""
        import jwt as jwt_lib

        fake_settings = _make_settings()
        claims_with_wrong_nonce = {
            "sub": "42",
            "nonce": "wrong-nonce",
        }

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwk_client = MagicMock()
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.PyJWKClient", return_value=mock_jwk_client),
            patch("app.core.oidc.jwt.decode", return_value=claims_with_wrong_nonce),
        ):
            with self.assertRaises(jwt_lib.InvalidTokenError) as ctx:
                await validate_id_token("fake.jwt.token", "expected-nonce")

        self.assertIn("nonce mismatch", str(ctx.exception))

    async def test_raises_when_nonce_missing_from_claims(self):
        """Lines 173-174: Missing nonce in claims also raises."""
        import jwt as jwt_lib

        fake_settings = _make_settings()
        claims_no_nonce = {"sub": "42"}

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwk_client = MagicMock()
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.PyJWKClient", return_value=mock_jwk_client),
            patch("app.core.oidc.jwt.decode", return_value=claims_no_nonce),
        ):
            with self.assertRaises(jwt_lib.InvalidTokenError):
                await validate_id_token("fake.jwt.token", "expected-nonce")

    async def test_jwk_client_receives_correct_jwks_uri(self):
        """Line 162: PyJWKClient is instantiated with discovery jwks_uri."""
        fake_settings = _make_settings()
        expected_claims = {"sub": "42", "nonce": "n"}

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwk_client = MagicMock()
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch(
                "app.core.oidc.PyJWKClient", return_value=mock_jwk_client
            ) as mock_cls,
            patch("app.core.oidc.jwt.decode", return_value=expected_claims),
        ):
            await validate_id_token("fake.jwt.token", "n")

        mock_cls.assert_called_once_with(FAKE_DISCOVERY["jwks_uri"])

    async def test_jwt_decode_uses_correct_algorithms_and_audience(self):
        """Lines 164-170: jwt.decode called with RS256/384/512, audience, issuer."""

        fake_settings = _make_settings()
        expected_claims = {"sub": "42", "nonce": "n"}

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwk_client = MagicMock()
        mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("app.core.oidc.get_effective_settings", return_value=fake_settings),
            patch(
                "app.core.oidc.get_oidc_discovery_document_for_settings",
                new_callable=AsyncMock,
                return_value=FAKE_DISCOVERY,
            ),
            patch("app.core.oidc.PyJWKClient", return_value=mock_jwk_client),
            patch("app.core.oidc.jwt.decode", return_value=expected_claims) as mock_decode,
        ):
            await validate_id_token("fake.jwt.token", "n")

        mock_decode.assert_called_once_with(
            "fake.jwt.token",
            "fake-key",
            algorithms=["RS256", "RS384", "RS512"],
            audience=fake_settings.oidc_client_id,
            issuer=FAKE_DISCOVERY["issuer"],
        )


# ---------------------------------------------------------------------------
# Required OIDC scopes
# ---------------------------------------------------------------------------

class TestRequiredOIDCScopes(unittest.TestCase):
    """Tests for get_required_oidc_scopes / get_required_oidc_scope_string."""

    def test_required_scopes_include_critical_values(self):
        scopes = get_required_oidc_scopes()
        for required in ("openid", "profile", "email"):
            self.assertIn(required, scopes)

    def test_scope_string_is_space_separated(self):
        scope_str = get_required_oidc_scope_string()
        self.assertIsInstance(scope_str, str)
        self.assertIn("openid", scope_str)
        parts = scope_str.split(" ")
        self.assertEqual(len(parts), len(set(parts)), "Duplicate scopes detected")


# ---------------------------------------------------------------------------
# HTTP error propagation tests
# ---------------------------------------------------------------------------

@patch("app.core.oidc.get_ssl_verify", return_value=True)
class TestHTTPErrorPropagation(unittest.IsolatedAsyncioTestCase):
    """Verify that httpx.HTTPStatusError propagates from HTTP-calling functions."""

    _EMPTY_CACHE = {"issuer": "", "expires_at": 0.0, "document": None}

    def setUp(self):
        oidc_mod._discovery_cache.update(self._EMPTY_CACHE)

    def tearDown(self):
        oidc_mod._discovery_cache.update(self._EMPTY_CACHE)

    async def test_discovery_raises_on_http_error(self, _mock_ssl):
        settings = _make_settings()
        resp = _make_httpx_response({}, status_code=500)
        mock_client = _make_async_client(resp)
        with patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client):
            with self.assertRaises(httpx.HTTPStatusError):
                await get_oidc_discovery_document_for_settings(settings)

    async def test_exchange_code_raises_on_http_error(self, _mock_ssl):
        settings = _make_settings()
        resp = _make_httpx_response({}, status_code=401)
        mock_client = _make_async_client(resp)
        with (
            patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client),
            patch("app.core.oidc.get_effective_settings", return_value=settings),
            patch.object(oidc_mod, "get_oidc_discovery_document_for_settings",
                         new_callable=AsyncMock, return_value=FAKE_DISCOVERY),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                await exchange_code_for_tokens("bad-code")

    async def test_exchange_refresh_raises_on_http_error(self, _mock_ssl):
        settings = _make_settings()
        resp = _make_httpx_response({}, status_code=400)
        mock_client = _make_async_client(resp)
        with (
            patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client),
            patch("app.core.oidc.get_effective_settings", return_value=settings),
            patch.object(oidc_mod, "get_oidc_discovery_document_for_settings",
                         new_callable=AsyncMock, return_value=FAKE_DISCOVERY),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                await exchange_refresh_token("bad-refresh-token")

    async def test_fetch_userinfo_raises_on_http_error(self, _mock_ssl):
        settings = _make_settings()
        resp = _make_httpx_response({}, status_code=403)
        mock_client = _make_async_client(resp)
        with (
            patch("app.core.oidc.httpx.AsyncClient", return_value=mock_client),
            patch("app.core.oidc.get_effective_settings", return_value=settings),
            patch.object(oidc_mod, "get_oidc_discovery_document_for_settings",
                         new_callable=AsyncMock, return_value=FAKE_DISCOVERY),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                await fetch_userinfo("bad-token")


if __name__ == "__main__":
    unittest.main()
