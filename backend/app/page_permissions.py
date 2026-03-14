"""Helpers for resolving dashboard page permissions."""

from __future__ import annotations

from typing import Optional

from app.config import Settings, get_effective_settings
from app.models import User

PAGE_PERMISSION_CONFIG_KEYS: dict[str, str] = {
    "monitor": "allow_monitor_for_users",
    "schedule_overview": "allow_schedule_overview_for_users",
    "analytics": "allow_analytics_for_users",
    "oidc_diagnostics": "allow_oidc_diagnostics_for_users",
}


def get_page_permissions(
    user: Optional[User],
    settings: Optional[Settings] = None,
) -> dict[str, bool]:
    """Resolve page permissions for the current user."""
    settings = settings or get_effective_settings()
    if not settings.oidc_enabled:
        return {page_key: True for page_key in PAGE_PERMISSION_CONFIG_KEYS}

    if user is None:
        return {page_key: False for page_key in PAGE_PERMISSION_CONFIG_KEYS}

    if user.platform_role == "platform_admin":
        return {page_key: True for page_key in PAGE_PERMISSION_CONFIG_KEYS}

    permissions: dict[str, bool] = {}
    for page_key, config_key in PAGE_PERMISSION_CONFIG_KEYS.items():
        permissions[page_key] = bool(getattr(settings, config_key))
    return permissions


def can_access_page(
    page_key: str,
    user: Optional[User],
    settings: Optional[Settings] = None,
) -> bool:
    """Check whether the user can access a page."""
    permissions = get_page_permissions(user, settings)
    return bool(permissions.get(page_key, False))
