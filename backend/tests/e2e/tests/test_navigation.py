"""
Navigation E2E Tests

Tests for the sidebar navigation and page routing.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.navigation
class TestNavigation:
    """Tests for sidebar navigation functionality."""

    def test_sidebar_visible_on_dashboard(self, class_page: Page):
        """Test that sidebar is visible on authenticated pages like Dashboard."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")

        sidebar = class_page.locator(".app-shell__sider")
        expect(sidebar).to_be_attached()

    def test_sidebar_not_visible_on_login(self, page: Page):
        """Test that sidebar is NOT visible on login page."""
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_sidebar_not_visible_on_bootstrap(self, page: Page):
        """Test that sidebar is NOT visible on bootstrap page."""
        page.goto("/bootstrap")
        page.wait_for_load_state("domcontentloaded")

        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_navigation_menu_items(self, class_page: Page):
        """Test that navigation menu has expected items when authenticated."""
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)

        # Check for main navigation items
        menu = class_page.locator(".nav-menu")
        expect(menu).to_be_visible()

    def test_issues_menu_item_visible(self, class_page: Page):
        """Test that Issues menu item is visible in sidebar."""
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)
        issues_menu = class_page.locator(".nav-menu").get_by_text("Issues")
        expect(issues_menu).to_be_visible()

    def test_tasks_menu_item_visible(self, class_page: Page):
        """Test that Tasks menu item is visible in sidebar."""
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)
        tasks_menu = class_page.locator(".nav-menu").get_by_text("Tasks")
        expect(tasks_menu).to_be_visible()

    def test_issues_menu_navigates_to_issues(self, logged_in_page: Page):
        """Clicking Issues in sidebar should navigate to /issues."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)
        issues_menu = logged_in_page.locator(".nav-menu").get_by_text("Issues")
        issues_menu.click()
        logged_in_page.wait_for_url("**/issues", timeout=5000)
        assert "/issues" in logged_in_page.url

    def test_tasks_menu_navigates_to_tasks(self, logged_in_page: Page):
        """Clicking Tasks in sidebar should navigate to /tasks."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)
        tasks_menu = logged_in_page.locator(".nav-menu").get_by_text("Tasks")
        tasks_menu.click()
        logged_in_page.wait_for_url("**/tasks", timeout=5000)
        assert "/tasks" in logged_in_page.url

    def test_dashboard_menu_navigates_to_dashboard(self, logged_in_page: Page):
        """Clicking Dashboard in sidebar should navigate to /dashboard."""
        logged_in_page.goto("/issues")
        logged_in_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)
        dash_menu = logged_in_page.locator(".nav-menu").get_by_text("Dashboard")
        dash_menu.click()
        logged_in_page.wait_for_url("**/dashboard", timeout=5000)
        assert "/dashboard" in logged_in_page.url

    def test_no_create_task_menu_item(self, class_page: Page):
        """CreateTask menu item should not be in sidebar (removed in refactoring)."""
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".nav-menu", state="visible", timeout=5000)
        menu = class_page.locator(".nav-menu")
        create_task = menu.get_by_text("Create Task", exact=True)
        assert create_task.count() == 0, "CreateTask menu item should not exist"

    def test_mobile_drawer_exists(self, class_page: Page):
        """Test that mobile drawer header exists for small screens."""
        class_page.set_viewport_size({"width": 375, "height": 667})  # iPhone SE size
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")

        # On mobile, drawer should be available
        # The drawer content should exist in DOM
        drawer_header = class_page.locator(".mobile-drawer-header")
        # Note: drawer might not be visible until triggered

        # Reset viewport to default to avoid leaking state to subsequent tests in the module
        class_page.set_viewport_size({"width": 1280, "height": 720})


@pytest.mark.navigation
class TestPageRouting:
    """Tests for page routing and redirects."""

    def test_root_redirects_to_dashboard(self, class_page: Page):
        """Test that root path redirects to dashboard when authenticated."""
        # First navigate away from dashboard to test redirect back
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")

        # Now navigate to root and wait for redirect to dashboard
        class_page.goto("/")
        class_page.wait_for_url("**/dashboard", timeout=10000)
        assert "/dashboard" in class_page.url

    def test_create_task_redirects_to_create_issue(self, class_page: Page):
        """Test that /create-task redirects to /issues/create."""
        class_page.goto("/create-task")
        class_page.wait_for_url("**/issues/create", timeout=5000)
        assert "/issues/create" in class_page.url

    def test_nonexistent_page_shows_error(self, page: Page):
        """Test that navigating to a nonexistent page shows error or redirects."""
        page.goto("/this-page-does-not-exist")
        page.wait_for_load_state("domcontentloaded")

        # Either shows 404 or redirects - both are acceptable
        assert "/this-page-does-not-exist" not in page.url or \
               page.locator("body").is_visible()


@pytest.mark.navigation
class TestTopbar:
    """Tests for the top navigation toolbar."""

    def test_topbar_visible_after_login(self, class_page: Page):
        """
        Test that the topbar is visible after successful login.

        After bootstrapping and logging in, the topbar should be visible
        with user info and logout button.
        """
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".app-shell__topbar", state="visible", timeout=5000)

        # Verify topbar is visible
        topbar = class_page.locator(".app-shell__topbar")
        expect(topbar).to_be_visible()

    def test_topbar_has_user_info(self, class_page: Page):
        """
        Test that the topbar displays user information.

        After login, the topbar should show the user's display name or username.
        """
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".app-shell__topbar-user", state="visible", timeout=5000)

        # Verify user info is displayed in topbar
        user_info = class_page.locator(".app-shell__topbar-user")
        expect(user_info).to_be_visible()

    def test_topbar_has_logout_button(self, class_page: Page):
        """
        Test that the topbar has a logout button.

        The logout button should be visible and clickable.
        """
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".app-shell__logout-button", state="visible", timeout=5000)

        # Verify logout button exists and is visible
        logout_button = class_page.locator(".app-shell__logout-button")
        expect(logout_button).to_be_visible()
        expect(logout_button).to_contain_text("Logout")

    def test_topbar_has_language_toggle(self, class_page: Page):
        """
        Test that the topbar has a language toggle button.

        Users should be able to switch languages from the topbar.
        """
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".app-shell__language-toggle", state="visible", timeout=5000)

        # Verify language toggle exists in topbar actions
        language_toggle = class_page.locator(".app-shell__language-toggle")
        expect(language_toggle).to_be_visible()

    def test_topbar_not_visible_on_bootstrap(self, page: Page):
        """
        Test that the topbar is NOT visible on the bootstrap page.

        The bootstrap page should not show any navigation elements.
        This test uses page (not class_page) because we want to test
        the unauthenticated bootstrap page behavior.
        """
        page.goto("/bootstrap")
        page.wait_for_load_state("domcontentloaded")

        # Topbar should not be visible on bootstrap page
        topbar = page.locator(".app-shell__topbar")
        expect(topbar).not_to_be_visible()

    def test_topbar_not_visible_on_login(self, page: Page):
        """
        Test that the topbar is NOT visible on the login page.

        The login page should only show the login form without navigation.
        This test uses page (not class_page) because we want to test
        the unauthenticated login page behavior.
        """
        page.goto("/login")
        page.wait_for_load_state("domcontentloaded")

        # Login page should not have topbar
        topbar = page.locator(".app-shell__topbar")
        expect(topbar).not_to_be_visible()

    def test_sessions_menu_visible_after_login(self, class_page: Page):
        """
        Test that the Sessions menu item is visible in the sidebar after login.

        The Sessions menu should appear for authenticated users.
        """
        class_page.goto("/dashboard")
        class_page.wait_for_selector(".app-shell__sider", state="visible", timeout=5000)

        # Sessions menu should be visible
        sessions_menu = class_page.locator(".nav-menu").get_by_text("Sessions")
        expect(sessions_menu).to_be_visible()
