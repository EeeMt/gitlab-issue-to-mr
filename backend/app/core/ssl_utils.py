"""SSL/TLS utility helpers for HTTP clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from app.config import Settings


def get_ssl_verify(settings: Settings | None = None) -> Union[str, bool]:
    """Return the SSL verification parameter for httpx/requests.

    Returns the path to the custom CA bundle when ``CUSTOM_CA_BUNDLE`` is
    configured, or ``True`` (use system CA store) otherwise.

    Args:
        settings: Settings instance. If None, ``get_effective_settings()`` is
            called automatically.

    Returns:
        str path to CA bundle, or True for default system verification.
    """
    if settings is None:
        from app.config import get_effective_settings

        settings = get_effective_settings()
    if settings.custom_ca_bundle:
        return settings.custom_ca_bundle
    return True
