"""
Access Management E2E Tests

Tests for the access management page where admins can manage user roles.
"""

import pytest
from playwright.sync_api import Page, expect

# Modifies shared user/role state; requires serial execution.
# Run with: make test-e2e-serial
pytestmark = pytest.mark.serial



@pytest.mark.access
class TestAccessManagement:
    """Tests for the access management logged_in_page."""

    @pytest.fixture(autouse=True)
    def extra_viewer_user(self, db_cursor, logged_in_page):
        """Insert a second user so the Save Access button is enabled for someone other than self."""
        import hashlib
        salt = "test_salt_viewer"
        digest = hashlib.pbkdf2_hmac("sha256", b"SecurePass123!", salt.encode(), 1).hex()
        password_hash = f"pbkdf2_sha256$1${salt}${digest}"
        db_cursor.execute(
            """
            INSERT INTO users (
                username, display_name, email, auth_provider, local_password_hash,
                platform_role, platform_role_source, state, created_at, updated_at
            ) VALUES (
                'test_viewer', 'Test Viewer', 'viewer@test.example.com', 'local',
                %s, 'platform_user', 'manual', 'active', NOW(), NOW()
            )
            ON CONFLICT (username) DO NOTHING
            """,
            (password_hash,),
        )
        yield

    def _change_viewer_role(self, page: Page) -> None:
        """Helper: find the test_viewer card, change role to trigger dirty state."""
        # Wait for both user cards to be visible
        page.wait_for_selector(".user-management__card:nth-child(2)", state="visible", timeout=10000)

        # Find the viewer's card by display name and click its role select
        viewer_card = page.locator(".user-management__card").filter(has_text="Test Viewer")
        role_select = viewer_card.locator(".n-select").first
        role_select.locator(".n-base-selection").click()

        # Wait for dropdown portal; pick first option (Platform admin) scoped to the menu
        menu = page.locator(".n-base-select-menu")
        menu.wait_for(state="visible", timeout=5000)
        menu.locator(".n-base-select-option").first.click()
        # Give Vue one tick to process the selection before proceeding
        page.wait_for_timeout(300)

    def test_update_user_role_success(self, logged_in_page: Page, reset_database):
        """Test that updating a user's role shows success message."""
        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("access-management-page")).to_be_visible()

        self._change_viewer_role(logged_in_page)

        # Save Access button for the viewer should now be enabled.
        save_buttons = logged_in_page.get_by_role("button", name="Save access")
        enabled_save = None
        for i in range(save_buttons.count()):
            btn = save_buttons.nth(i)
            if not btn.is_disabled():
                enabled_save = btn
                break
        assert enabled_save is not None, "Save Access button is still disabled after role change"
        enabled_save.click()

        # Wait for any toast message and verify it is a success (not error)
        logged_in_page.wait_for_selector(".n-message", state="visible", timeout=5000)
        assert logged_in_page.locator(".n-message--error").count() == 0, \
            "Error message appeared after saving role"
        assert "Updated access" in (logged_in_page.locator(".n-message").first.text_content() or ""), \
            "Expected success message text not found"

    def test_update_user_role_click_save_access(self, logged_in_page: Page, reset_database):
        """Test clicking Save Access button does not show an error."""
        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("access-management-page")).to_be_visible()

        self._change_viewer_role(logged_in_page)

        save_buttons = logged_in_page.get_by_role("button", name="Save access")
        enabled_save = None
        for i in range(save_buttons.count()):
            btn = save_buttons.nth(i)
            if not btn.is_disabled():
                enabled_save = btn
                break
        assert enabled_save is not None, "Save Access button is still disabled after role change"
        enabled_save.click()

        # Verify no error message appeared.
        logged_in_page.wait_for_selector(".n-message", state="visible", timeout=5000)
        assert logged_in_page.locator(".n-message--error").count() == 0, \
            "Error message appeared after clicking Save Access"
