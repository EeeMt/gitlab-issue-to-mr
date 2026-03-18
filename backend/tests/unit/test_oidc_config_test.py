#!/usr/bin/env python3
"""Unit tests for OIDC config test endpoint with local auth support."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.models import User


class OIDCConfigTestEndpointTests(unittest.TestCase):
    """Test the /config/oidc/test endpoint behavior with different auth states."""

    def setUp(self):
        self.client = TestClient(app)

    def test_oidc_test_allows_unauthenticated_when_oidc_disabled(self):
        """When OIDC is not configured, allow unauthenticated test requests."""
        # Mock settings to show OIDC as disabled
        mock_settings = MagicMock()
        mock_settings.oidc_enabled = False
        
        with patch('app.api.config.get_effective_settings', return_value=mock_settings):
            with patch('app.api.config.load_runtime_config_from_db', new_callable=AsyncMock):
                with patch('app.api.config._build_preview_settings') as mock_build:
                    mock_build.return_value = mock_settings
                    with patch('app.api.config.get_oidc_discovery_document_for_settings', new_callable=AsyncMock) as mock_discovery:
                        mock_discovery.return_value = {
                            "issuer": "https://example.com",
                            "authorization_endpoint": "https://example.com/oauth/authorize",
                            "token_endpoint": "https://example.com/oauth/token",
                            "userinfo_endpoint": "https://example.com/userinfo",
                        }
                        with patch('app.api.config.build_authorization_url_for_settings', new_callable=AsyncMock) as mock_auth_url:
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

    def test_oidc_test_requires_auth_when_oidc_enabled_without_skip_header(self):
        """When OIDC is configured and no skip-redirect header, require auth."""
        mock_settings = MagicMock()
        mock_settings.oidc_enabled = True
        
        with patch('app.api.config.get_effective_settings', return_value=mock_settings):
            # Without skip-redirect header, should get 401
            response = self.client.post(
                "/api/config/oidc/test",
                json={"auth": {}}
            )
            
            # Should be 401 (unauthorized)
            self.assertEqual(response.status_code, 401)

    def test_oidc_test_allows_skip_redirect_when_oidc_enabled(self):
        """When OIDC is configured with skip-redirect header, allow the test."""
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
        
        with patch('app.api.config.get_effective_settings', return_value=mock_settings):
            with patch('app.api.config.load_runtime_config_from_db', new_callable=AsyncMock):
                with patch('app.api.config._normalize_updates', return_value={}):
                    with patch('app.api.config._build_preview_settings', return_value=mock_settings):
                        with patch('app.api.config.get_oidc_discovery_document_for_settings', new_callable=AsyncMock) as mock_discovery:
                            mock_discovery.return_value = {
                                "issuer": "https://example.com",
                                "authorization_endpoint": "https://example.com/oauth/authorize",
                                "token_endpoint": "https://example.com/oauth/token",
                                "userinfo_endpoint": "https://example.com/userinfo",
                            }
                            with patch('app.api.config.build_authorization_url_for_settings', new_callable=AsyncMock) as mock_auth_url:
                                mock_auth_url.return_value = "https://example.com/oauth/authorize?client_id=test"
                                
                                # With skip-redirect header, should allow the test
                                response = self.client.post(
                                    "/api/config/oidc/test",
                                    json={"auth": {}},
                                    headers={"X-Skip-Auth-Redirect": "true"}
                                )
                                
                                # Should succeed (200)
                                self.assertEqual(response.status_code, 200)
                                
                                # Should return expected fields
                                data = response.json()
                                self.assertIn("issuer", data)
                                self.assertIn("authorization_endpoint", data)
                                self.assertIn("authorization_url_preview", data)
                                self.assertIn("required_scopes", data)
                                self.assertIn("warnings", data)


class OIDCConfigTestWithLocalAuthTests(unittest.TestCase):
    """Test OIDC config test endpoint with locally authenticated users."""

    def setUp(self):
        self.client = TestClient(app)

    def test_oidc_test_works_with_locally_authenticated_admin(self):
        """Locally authenticated admin users can test OIDC configuration."""
        # Create a mock locally authenticated admin user
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.display_name = "Administrator"
        mock_user.email = "admin@example.com"
        mock_user.platform_role = "platform_admin"
        mock_user.auth_provider = "local"
        
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
        
        with patch('app.api.config.get_effective_settings', return_value=mock_settings):
            with patch('app.api.config.load_runtime_config_from_db', new_callable=AsyncMock):
                with patch('app.api.config.require_admin_user', return_value=mock_user):
                    with patch('app.api.config._normalize_updates', return_value={}):
                        with patch('app.api.config._build_preview_settings', return_value=mock_settings):
                            with patch('app.api.config.get_oidc_discovery_document_for_settings', new_callable=AsyncMock) as mock_discovery:
                                mock_discovery.return_value = {
                                    "issuer": "https://example.com",
                                    "authorization_endpoint": "https://example.com/oauth/authorize",
                                    "token_endpoint": "https://example.com/oauth/token",
                                    "userinfo_endpoint": "https://example.com/userinfo",
                                }
                                with patch('app.api.config.build_authorization_url_for_settings', new_callable=AsyncMock) as mock_auth_url:
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


if __name__ == "__main__":
    unittest.main()
