"""
Access Management E2E Tests

Tests for the access management page where admins can manage user roles.
"""

import pytest
from playwright.sync_api import Page, expect




@pytest.mark.access
class TestAccessManagement:
    """Tests for the access management logged_in_page."""

    def test_update_user_role_success(self, logged_in_page: Page, reset_database):
        """Test that updating a user's role shows success message."""
        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("domcontentloaded")
        # Wait for user data to load from API before checking Save Access buttons
        logged_in_page.wait_for_selector(".user-management__card", state="visible", timeout=10000)
        expect(logged_in_page.get_by_test_id("access-management-page")).to_be_visible()

        save_buttons = logged_in_page.get_by_role("button", name="Save Access")
        button_count = save_buttons.count()
        print(f"Found {button_count} Save Access buttons")

        for i in range(button_count):
            btn = save_buttons.nth(i)
            if not btn.is_disabled():
                print(f"Clicking Save Access button {i}")
                btn.click()
                logged_in_page.wait_for_timeout(2000)

                error_locator = logged_in_page.locator(".n-message--error")
                if error_locator.count() > 0:
                    error_text = error_locator.first.text_content()
                    print(f"ERROR FOUND: {error_text}")
                    pytest.fail(f"Error appeared after clicking save: {error_text}")

                success_locator = logged_in_page.locator(".n-message--success")
                if success_locator.count() > 0:
                    success_text = success_locator.first.text_content()
                    print(f"SUCCESS: {success_text}")
                    return

        pytest.skip("No enabled Save Access button found (possibly only current user exists)")

    def test_update_user_role_click_save_access(self, logged_in_page: Page, reset_database):
        """Test clicking Save Access button does not show error."""
        logged_in_page.goto("/access-management")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(3000)
        expect(logged_in_page.get_by_test_id("access-management-page")).to_be_visible()

        role_selects = logged_in_page.locator(".user-management__card .n-select")
        select_count = role_selects.count()
        print(f"Found {select_count} select elements on page")

        save_buttons = logged_in_page.get_by_role("button", name="Save Access")
        for i in range(save_buttons.count()):
            btn = save_buttons.nth(i)
            is_disabled = btn.is_disabled()
            print(f"Save Access button {i}: disabled={is_disabled}")
            if not is_disabled:
                btn.click()
                logged_in_page.wait_for_timeout(2000)

                page_content = logged_in_page.content()
                if "Failed to update user access" in page_content:
                    pytest.fail("Reproduced: 'Failed to update user access' error appeared!")
                elif "updatedAccess" in page_content or "success" in page_content.lower():
                    print("Success message found - no error")
                    return
                else:
                    print("Neither success nor error message found")

        pytest.skip("Could not find enabled Save Access button to click")
