#!/usr/bin/env python3
"""Unit tests for configurable shared page permissions."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import Settings
from app.page_permissions import can_access_page, get_page_permissions


class _User:
    def __init__(self, platform_role: str) -> None:
        self.platform_role = platform_role


class PagePermissionTests(unittest.TestCase):
    def test_admin_can_access_all_shared_pages(self) -> None:
        settings = Settings(oidc_enabled=True)
        user = _User("platform_admin")

        permissions = get_page_permissions(user, settings)

        self.assertEqual(
            permissions,
            {
                "monitor": True,
                "schedule_overview": True,
                "analytics": True,
                "oidc_diagnostics": True,
            },
        )

    def test_platform_user_access_respects_runtime_switches(self) -> None:
        settings = Settings(
            oidc_enabled=True,
            allow_monitor_for_users=True,
            allow_schedule_overview_for_users=False,
            allow_analytics_for_users=True,
            allow_oidc_diagnostics_for_users=True,
        )
        user = _User("platform_user")

        permissions = get_page_permissions(user, settings)

        self.assertEqual(
            permissions,
            {
                "monitor": True,
                "schedule_overview": False,
                "analytics": True,
                "oidc_diagnostics": True,
            },
        )
        self.assertTrue(can_access_page("monitor", user, settings))
        self.assertFalse(can_access_page("schedule_overview", user, settings))
        self.assertTrue(can_access_page("analytics", user, settings))

    def test_unauthenticated_user_has_no_shared_page_access_when_oidc_enabled(self) -> None:
        settings = Settings(
            oidc_enabled=True,
            allow_monitor_for_users=True,
            allow_schedule_overview_for_users=True,
            allow_analytics_for_users=True,
            allow_oidc_diagnostics_for_users=True,
        )

        self.assertEqual(
            get_page_permissions(None, settings),
            {
                "monitor": False,
                "schedule_overview": False,
                "analytics": False,
                "oidc_diagnostics": False,
            },
        )

    def test_oidc_disabled_allows_all_pages(self) -> None:
        settings = Settings(oidc_enabled=False)

        self.assertEqual(
            get_page_permissions(None, settings),
            {
                "monitor": True,
                "schedule_overview": True,
                "analytics": True,
                "oidc_diagnostics": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
