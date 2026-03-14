"""Helpers for resolving dashboard user roles and states."""

from __future__ import annotations

from collections.abc import Set

from app.models import User

PLATFORM_ROLE_ADMIN = "platform_admin"
PLATFORM_ROLE_USER = "platform_user"
PLATFORM_ROLE_DISABLED = "disabled"

ROLE_SOURCE_BOOTSTRAP = "bootstrap"
ROLE_SOURCE_MANUAL = "manual"
ROLE_SOURCE_BREAK_GLASS = "break_glass"

USER_STATE_ACTIVE = "active"
USER_STATE_DISABLED = "disabled"

VALID_PLATFORM_ROLES = {PLATFORM_ROLE_ADMIN, PLATFORM_ROLE_USER}
VALID_USER_STATES = {USER_STATE_ACTIVE, USER_STATE_DISABLED}


def apply_platform_access_policy(
    user: User,
    *,
    username: str,
    groups: Set[str],
    admin_usernames: Set[str],
    admin_gitlab_groups: Set[str],
) -> None:
    """Resolve the effective platform role while preserving manual overrides."""
    if user.platform_role == PLATFORM_ROLE_DISABLED:
        user.platform_role = PLATFORM_ROLE_USER
        user.platform_role_source = ROLE_SOURCE_MANUAL
        user.state = USER_STATE_DISABLED

    if user.state == USER_STATE_DISABLED:
        return

    if user.platform_role_source in {ROLE_SOURCE_MANUAL, ROLE_SOURCE_BREAK_GLASS}:
        if user.platform_role not in VALID_PLATFORM_ROLES:
            user.platform_role = PLATFORM_ROLE_USER
        return

    if user.platform_role == PLATFORM_ROLE_ADMIN:
        return

    if username in admin_usernames or groups.intersection(admin_gitlab_groups):
        user.platform_role = PLATFORM_ROLE_ADMIN
    else:
        user.platform_role = PLATFORM_ROLE_USER
    user.platform_role_source = ROLE_SOURCE_BOOTSTRAP
