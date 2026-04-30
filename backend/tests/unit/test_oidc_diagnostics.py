#!/usr/bin/env python3
"""Unit tests for OIDC diagnostics helpers."""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.api.oidc import _build_endpoint_checks, _build_oidc_diagnostics_warnings
from app.core.oidc import get_required_oidc_scope_string, get_required_oidc_scopes


class OIDCDiagnosticsTests(unittest.TestCase):
    def test_required_scope_string_matches_gitlab_compatible_scopes(self) -> None:
        self.assertEqual(
            get_required_oidc_scopes(),
            ("openid", "profile", "email", "read_api"),
        )
        self.assertEqual(get_required_oidc_scope_string(), "openid profile email read_api")

    def test_diagnostics_warnings_cover_cookie_and_callback_shape(self) -> None:
        settings = SimpleNamespace(
            oidc_redirect_uri="http://example.com/wrong-path",
            cookie_secure=True,
            session_ttl_seconds=90000,
            cookie_samesite="none",
            break_glass_enabled=False,
            admin_gitlab_groups={"platform-team"},
        )

        warnings = _build_oidc_diagnostics_warnings(settings)

        self.assertTrue(any("/api/auth/callback" in warning for warning in warnings))
        self.assertTrue(any("COOKIE_SECURE=true" in warning for warning in warnings))
        self.assertTrue(any("24 hours" in warning for warning in warnings))
        self.assertTrue(any("Group-based admin bootstrap" in warning for warning in warnings))

    def test_diagnostics_warn_when_samesite_none_is_not_secure(self) -> None:
        settings = SimpleNamespace(
            oidc_redirect_uri="https://example.com/api/auth/callback",
            cookie_secure=False,
            session_ttl_seconds=3600,
            cookie_samesite="none",
            break_glass_enabled=True,
            admin_gitlab_groups=set(),
        )

        warnings = _build_oidc_diagnostics_warnings(settings)

        self.assertTrue(any("SameSite=None" in warning for warning in warnings))

    def test_endpoint_checks_report_missing_fields(self) -> None:
        checks = _build_endpoint_checks(
            {
                "authorization_endpoint": "https://gitlab.example.com/oauth/authorize",
                "token_endpoint": "",
                "userinfo_endpoint": "",
            }
        )

        status_by_key = {check.key: check.status for check in checks}
        self.assertEqual(status_by_key["authorization_endpoint"], "ok")
        self.assertEqual(status_by_key["token_endpoint"], "error")
        self.assertEqual(status_by_key["userinfo_endpoint"], "error")


if __name__ == "__main__":
    unittest.main()
