"""
App Shell E2E Tests

Tests for the application shell components including:
- Sidebar navigation links and routing
- Logout button visibility and redirect
- Language toggle visibility
"""

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.shell
class TestShellNavigation:
    """Tests that all sidebar menu links navigate to the correct pages."""

    def test_sidebar_dashboard_link(self, class_page: Page):
        """Test that clicking the Dashboard sidebar item navigates to /dashboard."""
        class_page.goto("/sessions")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.locator(".nav-menu").get_by_text("Dashboard", exact=True).first.click()
        expect(class_page).to_have_url(re.compile(r"/dashboard"), timeout=5000)

    def test_sidebar_sessions_link(self, class_page: Page):
        """Test that clicking the Sessions sidebar item navigates to /sessions."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.locator(".nav-menu").get_by_text("Sessions", exact=True).first.click()
        expect(class_page).to_have_url(re.compile(r"/sessions"), timeout=5000)

    def test_sidebar_monitor_link(self, class_page: Page):
        """Test that clicking the Monitor sidebar item navigates to /monitor."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        monitor_link = class_page.locator(".nav-menu").get_by_text("Monitor", exact=True).first
        if monitor_link.is_visible():
            monitor_link.click()
            expect(class_page).to_have_url(re.compile(r"/monitor"), timeout=5000)

    def test_sidebar_analytics_link(self, class_page: Page):
        """Test that clicking the Analytics sidebar item navigates to /analytics."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        analytics_link = class_page.locator(".nav-menu").get_by_text("Analytics", exact=True).first
        if analytics_link.is_visible():
            analytics_link.click()
            expect(class_page).to_have_url(re.compile(r"/analytics"), timeout=5000)

    def test_sidebar_config_link(self, class_page: Page):
        """Test that clicking the Config sidebar item navigates to /config."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        config_link = class_page.locator(".nav-menu").get_by_text("Config", exact=True).first
        if config_link.is_visible():
            config_link.click()
            expect(class_page).to_have_url(re.compile(r"/config"), timeout=5000)

    def test_sidebar_access_management_link(self, class_page: Page):
        """Test that clicking the Access Management sidebar item navigates to /access-management."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        access_link = class_page.locator(".nav-menu").get_by_text("Access Management", exact=True).first
        if access_link.is_visible():
            access_link.click()
            expect(class_page).to_have_url(re.compile(r"/access-management"), timeout=5000)


@pytest.mark.shell
class TestShellLogout:
    """Tests for the logout functionality in the app shell."""

    def test_logout_button_is_visible(self, class_page: Page):
        """Test that the logout button is visible in the topbar."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        logout_btn = class_page.locator(".app-shell__logout-button")
        expect(logout_btn).to_be_visible()

    def test_logout_redirects_to_login(self, fresh_page: Page):
        """Test that clicking the logout button redirects to the login page."""
        fresh_page.goto("/dashboard")
        fresh_page.wait_for_load_state("domcontentloaded")
        logout_btn = fresh_page.locator(".app-shell__logout-button")
        expect(logout_btn).to_be_visible()
        logout_btn.click()
        expect(fresh_page).to_have_url(re.compile(r"/login"), timeout=5000)


@pytest.mark.shell
class TestShellLanguage:
    """Tests for the language toggle in the app shell."""

    def test_language_toggle_is_visible(self, class_page: Page):
        """Test that the language toggle button is visible in the topbar."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        lang_toggle = class_page.locator(".app-shell__language-toggle")
        expect(lang_toggle).to_be_visible()
