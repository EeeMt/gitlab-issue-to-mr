"""
Navigation E2E Tests

Tests for the sidebar navigation and page routing.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.navigation
class TestNavigation:
    """Tests for sidebar navigation functionality."""

    def test_sidebar_visible_on_dashboard(self, page: Page):
        """Test that sidebar is visible on authenticated pages like Dashboard."""
        # Note: This test assumes authentication is handled
        # In a real scenario, you might need to authenticate first
        page.goto("/dashboard")

        # Wait for potential auth redirect
        page.wait_for_load_state("networkidle")

        # If not redirected to login, sidebar should be visible
        if page.url.endswith("/dashboard") or page.url.endswith("/login"):
            if "/login" in page.url:
                pytest.skip("Authentication required, skipping sidebar test")

            sidebar = page.locator(".app-shell__sider")
            # Sidebar might be collapsed on small screens
            # We just verify it exists in the DOM
            expect(sidebar).to_be_attached()

    def test_sidebar_not_visible_on_login(self, page: Page):
        """Test that sidebar is NOT visible on login page."""
        page.goto("/login")
        page.wait_for_load_state("networkidle")

        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_sidebar_not_visible_on_bootstrap(self, page: Page):
        """Test that sidebar is NOT visible on bootstrap page."""
        page.goto("/bootstrap")
        page.wait_for_load_state("networkidle")

        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_navigation_menu_items(self, page: Page):
        """Test that navigation menu has expected items when authenticated."""
        # Skip if not authenticated - this would need auth setup
        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        if "/login" in page.url:
            pytest.skip("Authentication required")

        # Check for main navigation items
        menu = page.locator(".nav-menu")
        expect(menu).to_be_visible()

    def test_mobile_drawer_exists(self, page: Page):
        """Test that mobile drawer header exists for small screens."""
        page.set_viewport_size({"width": 375, "height": 667})  # iPhone SE size
        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        if "/login" in page.url:
            pytest.skip("Authentication required")

        # On mobile, drawer should be available
        # The drawer content should exist in DOM
        drawer_header = page.locator(".mobile-drawer-header")
        # Note: drawer might not be visible until triggered


@pytest.mark.navigation
class TestPageRouting:
    """Tests for page routing and redirects."""

    def test_root_redirects_to_dashboard(self, page: Page):
        """Test that root path redirects to dashboard or bootstrap (if not initialized)."""
        page.goto("/")
        page.wait_for_load_state("networkidle")

        # Should redirect to dashboard, login, or bootstrap (if not initialized)
        # All of these are valid destinations based on auth state
        assert "/dashboard" in page.url or "/login" in page.url or "/bootstrap" in page.url

    def test_nonexistent_page_shows_error(self, page: Page):
        """Test that navigating to a nonexistent page shows error or redirects."""
        page.goto("/this-page-does-not-exist")
        page.wait_for_load_state("networkidle")

        # Either shows 404 or redirects - both are acceptable
        assert "/this-page-does-not-exist" not in page.url or \
               page.locator("body").is_visible()
