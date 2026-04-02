"""
OidcDiagnostics E2E Tests

Tests for the OIDC Diagnostics panel functionality.

The /oidc-diagnostics route redirects to /configuration?tab=auth where the
OidcDiagnosticsPanel component is embedded within the AuthSettingsPanel.
Tests navigate to /config?tab=auth and verify the diagnostics card structure.

Note: OIDC is likely disabled in the test environment, so we only assert on
panel structure (card header, title, button) and not on diagnostics content.
"""

import pytest
from playwright.sync_api import Page, expect


def _wait_for_oidc_diagnostics(page: Page):
    """Navigate to the auth settings tab and wait for the diagnostics card."""
    page.goto("/config?tab=auth")
    page.wait_for_selector(".diagnostics-card", timeout=10000)


@pytest.mark.oidc_diagnostics
class TestOidcDiagnosticsPage:
    """Tests for the OIDC Diagnostics panel within Config > Auth tab."""

    def test_oidc_diagnostics_page_loads(self, logged_in_page: Page, reset_database):
        """Test that navigating via /oidc-diagnostics redirect lands on the config auth tab."""
        logged_in_page.goto("/oidc-diagnostics")
        # Route redirects to /configuration?tab=auth
        logged_in_page.wait_for_selector(".diagnostics-card", timeout=10000)
        outer = logged_in_page.locator(".diagnostics-card")
        expect(outer.first).to_be_visible()

    def test_diagnostics_card_header_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the diagnostics card header section is visible."""
        _wait_for_oidc_diagnostics(logged_in_page)
        header = logged_in_page.locator(".diagnostics-card__header").first
        expect(header).to_be_visible()

    def test_diagnostics_card_title_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the diagnostics card title is visible."""
        _wait_for_oidc_diagnostics(logged_in_page)
        title = logged_in_page.locator(".diagnostics-card__title").first
        expect(title).to_be_visible()

    def test_fetch_diagnostics_button_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the Fetch Diagnostics button is visible within the diagnostics card."""
        _wait_for_oidc_diagnostics(logged_in_page)
        # The button is in the first diagnostics-card header
        fetch_button = logged_in_page.locator(".diagnostics-card").first.get_by_role("button").first
        expect(fetch_button).to_be_visible()

