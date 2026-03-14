#!/usr/bin/env python3
"""Unit tests for dashboard user role resolution."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.user_roles import (
    PLATFORM_ROLE_ADMIN,
    PLATFORM_ROLE_USER,
    ROLE_SOURCE_BOOTSTRAP,
    ROLE_SOURCE_MANUAL,
    USER_STATE_DISABLED,
    apply_platform_access_policy,
)
from app.models import User


class UserRolePolicyTests(unittest.TestCase):
    def test_bootstrap_admin_is_granted_from_username(self) -> None:
        user = User(
            oidc_sub="1",
            gitlab_user_id=1,
            username="alice",
            platform_role=PLATFORM_ROLE_USER,
            platform_role_source=ROLE_SOURCE_BOOTSTRAP,
            state="active",
        )

        apply_platform_access_policy(
            user,
            username="alice",
            groups=set(),
            admin_usernames={"alice"},
            admin_gitlab_groups=set(),
        )

        self.assertEqual(user.platform_role, PLATFORM_ROLE_ADMIN)
        self.assertEqual(user.platform_role_source, ROLE_SOURCE_BOOTSTRAP)

    def test_manual_override_is_preserved_even_if_bootstrap_matches(self) -> None:
        user = User(
            oidc_sub="1",
            gitlab_user_id=1,
            username="alice",
            platform_role=PLATFORM_ROLE_USER,
            platform_role_source=ROLE_SOURCE_MANUAL,
            state="active",
        )

        apply_platform_access_policy(
            user,
            username="alice",
            groups=set(),
            admin_usernames={"alice"},
            admin_gitlab_groups=set(),
        )

        self.assertEqual(user.platform_role, PLATFORM_ROLE_USER)
        self.assertEqual(user.platform_role_source, ROLE_SOURCE_MANUAL)

    def test_disabled_state_wins_over_role_resolution(self) -> None:
        user = User(
            oidc_sub="1",
            gitlab_user_id=1,
            username="alice",
            platform_role=PLATFORM_ROLE_ADMIN,
            platform_role_source=ROLE_SOURCE_BOOTSTRAP,
            state=USER_STATE_DISABLED,
        )

        apply_platform_access_policy(
            user,
            username="alice",
            groups={"platform-team"},
            admin_usernames=set(),
            admin_gitlab_groups={"platform-team"},
        )

        self.assertEqual(user.state, USER_STATE_DISABLED)
        self.assertEqual(user.platform_role, PLATFORM_ROLE_ADMIN)


if __name__ == "__main__":
    unittest.main()
