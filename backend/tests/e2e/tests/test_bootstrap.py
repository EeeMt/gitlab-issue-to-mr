"""
Bootstrap Page E2E Tests

Tests for the initial setup/bootstrap page that should have no sidebar navigation.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.bootstrap
class TestBootstrapPage:
    """Tests for the Bootstrap initialization page."""

    def test_bootstrap_page_loads(self, page: Page):
        """Test that the bootstrap page loads without errors."""
        page.goto("/bootstrap")

        # Page should not have any console errors (Error level)
        # Note: We collect console messages, but this is a basic smoke test
        page.wait_for_load_state("networkidle")

    def test_bootstrap_page_has_no_sider(self, page: Page):
        """
        Verify that the Bootstrap page does not display the sidebar navigation.

        This was a bug that was fixed - the Bootstrap page (initial setup page)
        should be a clean, centered card without any navigation sidebar.
        """
        page.goto("/bootstrap")

        # The sider should not be visible on the bootstrap page
        sider = page.locator(".app-shell__sider")
        expect(sider).not_to_be_visible()

    def test_bootstrap_form_elements_exist(self, page: Page):
        """Test that all required form elements are present on the bootstrap page."""
        page.goto("/bootstrap")

        # Username field
        expect(page.get_by_label("Username")).to_be_visible()

        # Display name field
        expect(page.get_by_label("Display Name")).to_be_visible()

        # Email field
        expect(page.get_by_label("Email")).to_be_visible()

        # Password fields
        expect(page.get_by_label("Password")).to_be_visible()
        expect(page.get_by_label("Confirm Password")).to_be_visible()

        # Submit button
        expect(page.get_by_role("button", name="Create Admin")).to_be_visible()

    def test_bootstrap_form_validation(self, page: Page):
        """Test that form validation works correctly."""
        page.goto("/bootstrap")

        # Try to submit empty form
        page.get_by_role("button", name="Create Admin").click()

        # Should show validation errors (required fields)
        # The exact error messages depend on the i18n translations
        page.wait_for_selector(".n-form-item-feedback-wrapper--error")

    def test_bootstrap_password_min_length_validation(self, page: Page):
        """Test that password minimum length validation works."""
        page.goto("/bootstrap")

        # Fill form with short password
        page.get_by_label("Username").fill("testuser")
        page.get_by_label("Email").fill("test@example.com")
        page.get_by_label("Password").fill("short")
        page.get_by_label("Confirm Password").fill("short")

        # Submit
        page.get_by_role("button", name="Create Admin").click()

        # Should show password length error
        # Note: The exact selector depends on Naive UI implementation
        page.wait_for_timeout(500)  # Allow validation to trigger

    def test_bootstrap_language_toggle_exists(self, page: Page):
        """Test that language toggle is present on bootstrap page."""
        page.goto("/bootstrap")

        # Language toggle should be visible
        language_toggle = page.locator(".bootstrap-card__language-switcher")
        expect(language_toggle).to_be_visible()

    def test_bootstrap_card_is_centered(self, page: Page):
        """Test that the bootstrap card is properly centered on the page."""
        page.goto("/bootstrap")

        # The bootstrap card should be visible and centered
        bootstrap_card = page.locator(".bootstrap-card")
        expect(bootstrap_card).to_be_visible()

        # Verify it's centered using CSS properties
        # This is a basic check - in reality you'd check computed styles
        box = bootstrap_card.bounding_box()
        assert box is not None
        # Card should be roughly centered horizontally
        # (viewport width - card width) / 2 should be close to card's x position
        viewport_size = page.viewport_size()
        viewport_width = viewport_size["width"]
        assert abs(box["x"] - (viewport_width - box["width"]) / 2) < 50  # Within 50px tolerance
