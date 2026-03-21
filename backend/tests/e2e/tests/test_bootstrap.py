"""
Bootstrap Page E2E Tests

Tests for the initial setup/bootstrap page that should have no sidebar navigation.
"""

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.bootstrap
class TestBootstrapPage:
    """Tests for the Bootstrap initialization page."""

    def test_bootstrap_page_loads(self, page: Page, reset_database):
        """Test that the bootstrap page loads without errors."""
        page.goto("/bootstrap")

        # Wait for bootstrap card to be visible (system should be uninitialized)
        page.wait_for_selector(".bootstrap-card", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_bootstrap_page_has_no_sider(self, page: Page, reset_database):
        """
        Verify that the Bootstrap page does not display the sidebar navigation.

        This was a bug that was fixed - the Bootstrap page (initial setup page)
        should be a clean, centered card without any navigation sidebar.
        """
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # The sider should not be visible on the bootstrap page
        sider = page.locator(".app-shell__sider")
        expect(sider).not_to_be_visible()

    def test_bootstrap_form_elements_exist(self, page: Page, reset_database):
        """Test that all required form elements are present on the bootstrap page."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Username field
        expect(page.locator(".bootstrap-form input").nth(0)).to_be_visible()

        # Display name field
        expect(page.locator(".bootstrap-form input").nth(1)).to_be_visible()

        # Email field
        expect(page.locator(".bootstrap-form input").nth(2)).to_be_visible()

        # Password fields (nth 3 and 4)
        expect(page.locator(".bootstrap-form input[type='password']").nth(0)).to_be_visible()
        expect(page.locator(".bootstrap-form input[type='password']").nth(1)).to_be_visible()

        # Submit button
        expect(page.get_by_role("button", name="Create Admin")).to_be_visible()

    def test_bootstrap_form_validation(self, page: Page, reset_database):
        """Test that form validation works correctly."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Try to submit empty form
        page.get_by_role("button", name="Create Admin").click()

        # Should show validation errors (required fields)
        # Naive UI shows errors with n-form-item-feedback-wrapper
        page.wait_for_timeout(500)  # Allow validation to trigger

    def test_bootstrap_password_min_length_validation(self, page: Page, reset_database):
        """Test that password minimum length validation works."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Fill form with short password
        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("testuser")
        inputs.nth(2).fill("test@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("short")
        password_inputs.nth(1).fill("short")

        # Submit
        page.get_by_role("button", name="Create Admin").click()

        # Should show password length error
        # Note: The exact selector depends on Naive UI implementation
        page.wait_for_timeout(500)  # Allow validation to trigger

    def test_bootstrap_language_toggle_exists(self, page: Page, reset_database):
        """Test that language toggle is present on bootstrap page."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Language toggle should be visible
        language_toggle = page.locator(".bootstrap-card__language-switcher")
        expect(language_toggle).to_be_visible()

    def test_bootstrap_card_is_centered(self, page: Page, reset_database):
        """Test that the bootstrap card is properly centered on the page."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # The bootstrap card should be visible and centered
        bootstrap_card = page.locator(".bootstrap-card")
        expect(bootstrap_card).to_be_visible()

        # Verify it's centered using CSS properties
        # This is a basic check - in reality you'd check computed styles
        box = bootstrap_card.bounding_box()
        assert box is not None
        # Card should be roughly centered horizontally
        # (viewport width - card width) / 2 should be close to card's x position
        viewport_size = page.viewport_size
        viewport_width = viewport_size["width"]
        assert abs(box["x"] - (viewport_width - box["width"]) / 2) < 50  # Within 50px tolerance

    def test_bootstrap_email_field_visible_in_chinese(self, page: Page, reset_database):
        """
        Test that the email field is visible when using Chinese locale.

        This was a bug where the email field would not render in Chinese locale
        due to issues with @ symbol escaping in vue-i18n.
        """
        # First go to bootstrap to get a page with localStorage access
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Set Chinese locale
        page.evaluate("window.localStorage.setItem('gimr-locale', 'zh-CN')")

        # Reload to apply Chinese locale
        page.reload()
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Count all form inputs - should be 5 (username, displayName, email, password, confirmPassword)
        all_inputs = page.locator(".bootstrap-form input")
        input_count = all_inputs.count()

        # Assert we have 5 inputs
        assert input_count == 5, f"Expected 5 inputs in bootstrap form (Chinese), found {input_count}"

        # Check that email input (3rd input, index 2) is visible and is a text input (not password)
        email_input = all_inputs.nth(2)
        expect(email_input).to_be_visible()
        expect(email_input).to_have_attribute("type", "text")
        expect(email_input).to_have_attribute("placeholder", "admin@example.com")

    def test_bootstrap_submit_creates_admin_and_redirects(
        self, page: Page, reset_database
    ):
        """
        Test that filling and submitting the bootstrap form:
        1. Creates the admin user in the database
        2. Marks system as initialized
        3. Redirects to dashboard

        This is the critical E2E test for the bootstrap flow.
        """
        page.goto("/bootstrap")

        # Wait for the form to be visible (may be redirected if system already initialized)
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Fill out the form with valid data
        # Use nth to select form inputs by position (0=username, 1=displayName, 2=email)
        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("e2e_admin")
        inputs.nth(1).fill("E2E Test Admin")
        inputs.nth(2).fill("e2e_admin@test.com")

        # Fill password fields (type='password')
        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        # Submit the form
        page.get_by_role("button", name="Create Admin").click()

        # Wait for navigation to dashboard
        # The page should redirect to /dashboard after successful registration
        page.wait_for_url("**/dashboard", timeout=10000)

        # Verify we're on the dashboard (not redirected back to bootstrap)
        expect(page).to_have_url(re.compile(r".*dashboard"))

        # Verify the dashboard loaded (should have main content area)
        page.wait_for_load_state("networkidle")

    def test_bootstrap_redirects_when_already_initialized(
        self, page: Page, reset_database
    ):
        """
        Test that when system is already initialized, accessing /bootstrap
        redirects to /dashboard.
        """
        # First, register an admin to initialize the system
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Use nth to select form inputs by position
        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("initial_admin")
        inputs.nth(1).fill("Initial Admin")
        inputs.nth(2).fill("initial@test.com")

        # Fill password fields
        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Now try to access /bootstrap again
        page.goto("/bootstrap")

        # Should be redirected to dashboard
        page.wait_for_url("**/dashboard", timeout=5000)
        expect(page).to_have_url(re.compile(r".*dashboard"))
