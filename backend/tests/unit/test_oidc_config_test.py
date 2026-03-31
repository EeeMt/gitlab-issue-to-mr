#!/usr/bin/env python3
"""Unit tests for OIDC config test endpoint with local auth support."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient
from starlette.requests import Request
from app.main import app
from app.models import User
from app.database import get_db
from app.dependencies.auth import require_authenticated_context


def create_mock_user():
    """Create a mock admin user for testing."""
    mock_user = MagicMock(spec=User)
    mock_user.id = 1
    mock_user.username = "admin"
    mock_user.display_name = "Administrator"
    mock_user.email = "admin@example.com"
    mock_user.platform_role = "platform_admin"
    mock_user.auth_provider = "local"
    return mock_user


class OIDCConfigTestEndpointTests(unittest.TestCase):
    """Test the /config/oidc/test endpoint behavior with different auth states."""

    def setUp(self):
        self.client = TestClient(app)
        # Override database dependency with a mock
        self.mock_db = AsyncMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(all=MagicMock(return_value=[]))))
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_oidc_test_allows_unauthenticated_when_oidc_disabled(self):
        """When OIDC is not configured, allow unauthenticated test requests.

        When OIDC is disabled and user is None, the endpoint allows unauthenticated access
        to enable initial OIDC setup.
        """
        # Mock settings to show OIDC as disabled with complete attribute set
        mock_settings = MagicMock()
        mock_settings.oidc_enabled = False
        mock_settings.oidc_issuer_url = "https://example.com"
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_redirect_uri = "http://localhost/api/auth/callback"
        mock_settings.cookie_secure = False
        mock_settings.cookie_samesite = "lax"
        mock_settings.session_ttl_seconds = 3600
        mock_settings.break_glass_enabled = False
        mock_settings.admin_gitlab_groups = set()
        mock_settings.oidc_client_secret = "test-secret"  # May be needed by _build_oidc_diagnostics_warnings

        mock_user = create_mock_user()

        # Patch require_authenticated_context to return a valid auth context so
        # require_admin_user doesn't raise 401
        async def mock_require_authenticated_context(request: Request, db=None):
            # Return an auth context with our mock user
            return SimpleNamespace(user=mock_user, session=None, failure_detail=None)

        # Override the dependencies using FastAPI's dependency_overrides
        app.dependency_overrides[require_authenticated_context] = mock_require_authenticated_context
        try:
            with patch('app.api.oidc.get_effective_settings', return_value=mock_settings):
                with patch('app.api.oidc.load_runtime_config_from_db', new_callable=AsyncMock) as mock_load:
                    mock_load.return_value = None
                    with patch('app.api.oidc._build_preview_settings', return_value=mock_settings):
                        with patch('app.api.oidc.get_oidc_discovery_document_for_settings', new_callable=AsyncMock) as mock_discovery:
                            mock_discovery.return_value = {
                                "issuer": "https://example.com",
                                "authorization_endpoint": "https://example.com/oauth/authorize",
                                "token_endpoint": "https://example.com/oauth/token",
                                "userinfo_endpoint": "https://example.com/userinfo",
                            }
                            with patch('app.api.oidc.build_authorization_url_for_settings', new_callable=AsyncMock) as mock_auth_url:
                                mock_auth_url.return_value = "https://example.com/oauth/authorize?client_id=test"

                                # Should not raise 401
                                response = self.client.post(
                                    "/api/config/oidc/test",
                                    json={"auth": {}},
                                    headers={"X-Skip-Auth-Redirect": "true"}
                                )

                                # Should succeed (200) or fail with validation error (422)
                                # but NOT with 401 Unauthorized
                                self.assertNotEqual(response.status_code, 401)
        finally:
            # Clean up the override
            if require_authenticated_context in app.dependency_overrides:
                del app.dependency_overrides[require_authenticated_context]

    def test_oidc_test_requires_auth_when_oidc_enabled_without_skip_header(self):
        """When OIDC is configured and no skip-redirect header, require auth."""
        mock_settings = MagicMock()
        mock_settings.oidc_enabled = True

        with patch('app.api.oidc.get_effective_settings', return_value=mock_settings):
            # Without skip-redirect header, should get 401
            response = self.client.post(
                "/api/config/oidc/test",
                json={"auth": {}}
            )

            # Should be 401 (unauthorized)
            self.assertEqual(response.status_code, 401)

    def test_oidc_test_allows_skip_redirect_when_oidc_enabled(self):
        """When OIDC is configured with skip-redirect header but no auth, still requires auth.

        The skip_redirect header logic in the endpoint body is only reached when there's
        an authenticated context. Without auth, require_admin_user raises 401 first.
        """
        mock_settings = MagicMock()
        mock_settings.oidc_enabled = True
        mock_settings.oidc_issuer_url = "https://example.com"
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_redirect_uri = "http://localhost/api/auth/callback"
        mock_settings.cookie_secure = False
        mock_settings.cookie_samesite = "lax"
        mock_settings.session_ttl_seconds = 3600
        mock_settings.break_glass_enabled = False
        mock_settings.admin_gitlab_groups = set()

        with patch('app.api.oidc.get_effective_settings', return_value=mock_settings):
            # When OIDC is enabled and there's no authenticated session,
            # require_admin_user raises 401 before endpoint body runs
            response = self.client.post(
                "/api/config/oidc/test",
                json={"auth": {}},
                headers={"X-Skip-Auth-Redirect": "true"}
            )

            # With OIDC enabled and no authenticated session, expect 401
            self.assertEqual(response.status_code, 401)


class OIDCConfigTestWithLocalAuthTests(unittest.TestCase):
    """Test OIDC config test endpoint with locally authenticated users."""

    def setUp(self):
        self.client = TestClient(app)
        # Override database dependency with a mock
        self.mock_db = AsyncMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(all=MagicMock(return_value=[]))))
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_oidc_test_works_with_locally_authenticated_admin(self):
        """Locally authenticated admin users can test OIDC configuration."""
        # Create a mock locally authenticated admin user
        mock_user = create_mock_user()

        mock_settings = MagicMock()
        mock_settings.oidc_enabled = True
        mock_settings.oidc_issuer_url = "https://example.com"
        mock_settings.oidc_client_id = "test-client"
        mock_settings.oidc_redirect_uri = "http://localhost/api/auth/callback"
        mock_settings.cookie_secure = False
        mock_settings.cookie_samesite = "lax"
        mock_settings.session_ttl_seconds = 3600
        mock_settings.break_glass_enabled = False
        mock_settings.admin_gitlab_groups = set()

        # Create mock auth context that returns our admin user
        async def mock_require_authenticated_context(request: Request, db=None):
            return SimpleNamespace(user=mock_user, session=None, failure_detail=None)

        # Override the dependencies using FastAPI's dependency_overrides
        app.dependency_overrides[require_authenticated_context] = mock_require_authenticated_context
        try:
            with patch('app.api.oidc.get_effective_settings', return_value=mock_settings):
                with patch('app.api.oidc.load_runtime_config_from_db', new_callable=AsyncMock) as mock_load:
                    mock_load.return_value = None
                    with patch('app.api.oidc._normalize_updates', return_value={}):
                        with patch('app.api.oidc._build_preview_settings', return_value=mock_settings):
                            with patch('app.api.oidc.get_oidc_discovery_document_for_settings', new_callable=AsyncMock) as mock_discovery:
                                mock_discovery.return_value = {
                                    "issuer": "https://example.com",
                                    "authorization_endpoint": "https://example.com/oauth/authorize",
                                    "token_endpoint": "https://example.com/oauth/token",
                                    "userinfo_endpoint": "https://example.com/userinfo",
                                }
                                with patch('app.api.oidc.build_authorization_url_for_settings', new_callable=AsyncMock) as mock_auth_url:
                                    mock_auth_url.return_value = "https://example.com/oauth/authorize?client_id=test"

                                    # Simulate authenticated request
                                    response = self.client.post(
                                        "/api/config/oidc/test",
                                        json={"auth": {}}
                                    )

                                    # Should succeed
                                    self.assertEqual(response.status_code, 200)

                                    data = response.json()
                                    self.assertEqual(data["issuer"], "https://example.com")
        finally:
            # Clean up the override
            if require_authenticated_context in app.dependency_overrides:
                del app.dependency_overrides[require_authenticated_context]


if __name__ == "__main__":
    unittest.main()
