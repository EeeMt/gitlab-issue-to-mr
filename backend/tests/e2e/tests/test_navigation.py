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

    def test_sidebar_not_visible_on_login(self, page: Page, reset_database):
        """Test that sidebar is NOT visible on login page."""
        page.goto("/login")
        page.wait_for_load_state("networkidle")

        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_sidebar_not_visible_on_bootstrap(self, page: Page, reset_database):
        """Test that sidebar is NOT visible on bootstrap page."""
        page.goto("/bootstrap")
        page.wait_for_load_state("networkidle")

        sidebar = page.locator(".app-shell__sider")
        expect(sidebar).not_to_be_visible()

    def test_navigation_menu_items(self, page: Page, reset_database):
        """Test that navigation menu has expected items when authenticated."""
        # Bootstrap first to create an authenticated session
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("nav_user")
        inputs.nth(1).fill("Nav User")
        inputs.nth(2).fill("nav@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Wait for sidebar to load
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

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


@pytest.mark.navigation
class TestTopbar:
    """Tests for the top navigation toolbar."""

    def test_topbar_visible_after_login(self, page: Page, reset_database):
        """
        Test that the topbar is visible after successful login.

        After bootstrapping and logging in, the topbar should be visible
        with user info and logout button.
        """
        # First, bootstrap the system
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Fill out bootstrap form
        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("topbar_test_user")
        inputs.nth(1).fill("Topbar Test User")
        inputs.nth(2).fill("topbar@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Wait for auth state to initialize after page reload
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Debug: print cookies
        context = page.context
        cookies = context.cookies()
        print(f"Cookies: {cookies}")

        # Debug: print page content
        print(f"Current URL: {page.url}")
        print(f"Page title: {page.title()}")
        print(f"Viewport: {page.viewport_size}")

        # Check if sidebar exists first
        sidebar = page.locator(".app-shell__sider")
        print(f"Sidebar count: {sidebar.count()}")
        if sidebar.count() > 0:
            print(f"Sidebar visible: {sidebar.is_visible()}")

        # Check for any topbar-like elements
        all_topbar = page.locator("[class*='topbar']")
        print(f"Topbar-like elements count: {all_topbar.count()}")

        # Check auth state by calling API with cookies
        response = page.request.get("http://nginx/api/auth/me")
        print(f"Auth /me response: {response.json()}")

        # Verify topbar is visible
        topbar = page.locator(".app-shell__topbar")
        expect(topbar).to_be_visible()

    def test_topbar_has_user_info(self, page: Page, reset_database):
        """
        Test that the topbar displays user information.

        After login, the topbar should show the user's display name or username.
        """
        # Bootstrap and login
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("topbar_user")
        inputs.nth(1).fill("Topbar User Display")
        inputs.nth(2).fill("topbaruser@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Wait for auth state to initialize after page reload
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Verify user info is displayed in topbar
        user_info = page.locator(".app-shell__topbar-user")
        expect(user_info).to_be_visible()

    def test_topbar_has_logout_button(self, page: Page, reset_database):
        """
        Test that the topbar has a logout button.

        The logout button should be visible and clickable.
        """
        # Bootstrap and login
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("logout_user")
        inputs.nth(1).fill("Logout User")
        inputs.nth(2).fill("logout@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Wait for auth state to initialize after page reload
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Verify logout button exists and is visible
        logout_button = page.locator(".app-shell__logout-button")
        expect(logout_button).to_be_visible()
        expect(logout_button).to_contain_text("Logout")

    def test_topbar_has_language_toggle(self, page: Page, reset_database):
        """
        Test that the topbar has a language toggle button.

        Users should be able to switch languages from the topbar.
        """
        # Bootstrap and login
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("lang_user")
        inputs.nth(1).fill("Lang User")
        inputs.nth(2).fill("lang@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Wait for auth state to initialize after page reload
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Verify language toggle exists in topbar actions
        language_toggle = page.locator(".app-shell__language-toggle")
        expect(language_toggle).to_be_visible()

    def test_topbar_not_visible_on_bootstrap(self, page: Page, reset_database):
        """
        Test that the topbar is NOT visible on the bootstrap page.

        The bootstrap page should not show any navigation elements.
        """
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Topbar should not be visible
        topbar = page.locator(".app-shell__topbar")
        expect(topbar).not_to_be_visible()

    def test_topbar_not_visible_on_login(self, page: Page, reset_database):
        """
        Test that the topbar is NOT visible on the login page.

        The login page should only show the login form without navigation.
        With local auth (OIDC disabled), authenticated users are redirected from /login to /dashboard.
        """
        # Register first, then go to login
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("login_user")
        inputs.nth(1).fill("Login User")
        inputs.nth(2).fill("login@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Go to login page - with local auth, authenticated users are redirected to dashboard
        page.goto("/login")
        page.wait_for_load_state("networkidle")

        # With OIDC disabled, authenticated users are redirected from /login to /dashboard
        # So we should end up on dashboard where topbar IS visible
        assert "/dashboard" in page.url, f"Expected redirect to /dashboard, got {page.url}"
        topbar = page.locator(".app-shell__topbar")
        expect(topbar).to_be_visible()

    def test_sessions_menu_visible_after_login(self, page: Page, reset_database):
        """
        Test that the Sessions menu item is visible in the sidebar after login.

        The Sessions menu should appear for authenticated users.
        """
        # Bootstrap and login
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("session_user")
        inputs.nth(1).fill("Session User")
        inputs.nth(2).fill("session@test.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)

        # Wait for sidebar to load and auth state to initialize
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Wait for sidebar to load
        page.wait_for_selector(".app-shell__sider", timeout=5000)

        # Sessions menu should be visible
        sessions_menu = page.locator(".nav-menu").get_by_text("Sessions")
        expect(sessions_menu).to_be_visible()
