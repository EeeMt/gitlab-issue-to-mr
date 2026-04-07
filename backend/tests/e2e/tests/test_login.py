"""
Login Page E2E Tests

Tests for the Login page functionality including:
- Page structure and card rendering
- Header and branding display
- Login form elements (tabs or password-toggle form)
- Error handling for invalid credentials
"""

import httpx
import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(scope="module")
def initialized_system(backend_url):
    """
    Ensure the system is initialized (has at least one admin user).

    The login page is only accessible when the system is initialized;
    otherwise the Vue router guard redirects to /bootstrap.  This fixture
    registers an admin via the backend API if the system hasn't been
    initialized yet.  A 403 response means another worker already
    initialized it — that's fine.
    """
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{backend_url}/api/auth/local/register",
            json={
                "username": "login_test_admin",
                "display_name": "Login Test Admin",
                "email": "login_test_admin@test.example.com",
                "password": "SecurePass123!",
            },
        )
        if resp.status_code not in (200, 201, 403):
            raise RuntimeError(
                f"Failed to initialize system for login tests: "
                f"{resp.status_code} {resp.text[:200]}"
            )


@pytest.mark.login
class TestLoginPage:
    """Tests for the login page structure and basic rendering."""

    def test_login_page_loads(self, page: Page, initialized_system):
        """Test that the login page loads and the outer container is visible."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_test_id("login-page")).to_be_visible()

    def test_login_card_is_visible(self, page: Page, initialized_system):
        """Test that the login card is rendered."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_test_id("login-card")).to_be_visible()

    def test_login_card_css_class(self, page: Page, initialized_system):
        """Test that the login card has the expected CSS class."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        expect(page.locator(".login-card")).to_be_visible()

    def test_login_header_is_visible(self, page: Page, initialized_system):
        """Test that the page header section is rendered."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_test_id("login-header")).to_be_visible()

    def test_login_page_has_authentication_ui(self, page: Page, initialized_system):
        """
        Test that the page shows some kind of authentication UI.

        Either login-tabs (when system not yet initialized) or
        the login-card__body (when system is already initialized).
        Both cases render inside login-card.
        """
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        # At least the card body (or tabs) must appear
        card = page.get_by_test_id("login-card")
        expect(card).to_be_visible()
        # Some child content must exist
        expect(card.locator("button, input").first).to_be_attached()

    def test_login_page_has_no_sidebar(self, page: Page, initialized_system):
        """Test that the sidebar is not visible on the login page."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_login_page_has_no_topbar(self, page: Page, initialized_system):
        """Test that the topbar is not visible on the login page."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        topbar = page.locator(".app-shell__topbar")
        expect(topbar).not_to_be_visible()

    def test_login_page_title_in_card(self, page: Page, initialized_system):
        """Test that the login card contains a title element."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")
        title = page.locator(".login-card__title")
        expect(title).to_be_visible()

    def test_login_tabs_or_password_toggle_present(self, page: Page, initialized_system):
        """
        Test that either bootstrap-style login tabs or the initialized
        password-toggle form is present.
        """
        page.goto("/login")
        page.wait_for_load_state("networkidle")
        tabs = page.get_by_test_id("login-tabs")
        toggle = page.locator(".login-card__toggle")
        # One or the other must be present in the DOM
        tabs_attached = tabs.count() > 0
        toggle_attached = toggle.count() > 0
        assert tabs_attached or toggle_attached, (
            "Expected either login-tabs or login-card__toggle to be in the DOM"
        )


@pytest.mark.login
class TestLoginErrors:
    """Tests for login error handling with invalid credentials."""

    def _reveal_password_form(self, page: Page):
        """
        Ensure the local-login form is visible.

        When the system is already initialized, the password form is hidden
        behind a toggle.  Click the toggle button to reveal it.
        When the system is not initialized yet, the form is inside login-tabs
        and already visible.
        """
        # Wait for the login card to render before checking form state
        page.wait_for_selector(".login-card", timeout=15000)

        # Case 1: system not initialized — form is inside login-tabs
        tabs = page.get_by_test_id("login-tabs")
        if tabs.is_visible(timeout=3000):
            return  # form elements are already accessible via login-username-input

        # Case 2: system initialized — toggle the password form open
        toggle_btn = page.locator(".login-card__toggle button")
        if toggle_btn.count() > 0 and toggle_btn.first.is_visible(timeout=3000):
            toggle_btn.first.click()
            # Wait for the password form to expand
            page.wait_for_selector(
                "[data-testid='login-password-toggle-username-input'],"
                "[data-testid='login-username-input']",
                timeout=10000,
            )

    def test_invalid_credentials_show_error(self, page: Page, initialized_system):
        """
        Test that submitting wrong credentials displays an error message.
        The error surfaces as an n-message toast from NaiveUI.
        """
        page.goto("/login", wait_until="networkidle")

        self._reveal_password_form(page)

        # Fill credentials — works for both initialized and uninitialized states
        username_sel = (
            "[data-testid='login-username-input'] input,"
            "[data-testid='login-password-toggle-username-input'] input"
        )
        password_sel = (
            "[data-testid='login-password-input'] input,"
            "[data-testid='login-password-toggle-password-input'] input"
        )
        submit_sel = (
            "[data-testid='login-submit-button'],"
            "[data-testid='login-password-toggle-submit-button']"
        )

        page.locator(username_sel).first.fill("wrong_user")
        page.locator(password_sel).first.fill("wrong_password")
        page.locator(submit_sel).first.click()

        # NaiveUI renders errors as .n-message elements
        error_message = page.locator(".n-message")
        expect(error_message).to_be_visible(timeout=8000)

    def test_empty_credentials_show_error(self, page: Page, initialized_system):
        """
        Test that submitting empty credentials shows an error or validation message.
        """
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        self._reveal_password_form(page)

        submit_sel = (
            "[data-testid='login-submit-button'],"
            "[data-testid='login-password-toggle-submit-button']"
        )
        page.locator(submit_sel).first.click()

        # Either an n-message toast or an n-form-item-feedback validation error
        error_indicator = page.locator(".n-message, .n-form-item-feedback")
        expect(error_indicator.first).to_be_visible(timeout=5000)
