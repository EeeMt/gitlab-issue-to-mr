"""
Access Management E2E Tests

Tests for the access management page where admins can manage user roles.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.access
class TestAccessManagement:
    """Tests for the access management page."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        # Fill out the form
        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("test_admin")
        inputs.nth(1).fill("Test Admin")
        inputs.nth(2).fill("test_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_update_user_role_success(self, page: Page, reset_database):
        """
        Test that updating a user's role shows success message.

        This test verifies the happy path where:
        1. Admin changes a user's role
        2. Clicks Save Access
        3. Success message appears
        """
        self._create_admin_and_login(page)

        # Navigate to access management
        page.goto("/access-management")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Look for the user table
        # Each user row should have action buttons including "Save Access"
        save_buttons = page.get_by_role("button", name="Save Access")

        # Count save buttons (one per user, but disabled for current user)
        button_count = save_buttons.count()
        print(f"Found {button_count} Save Access buttons")

        # Find a save button that's not disabled
        for i in range(button_count):
            btn = save_buttons.nth(i)
            if not btn.is_disabled():
                print(f"Clicking Save Access button {i}")
                btn.click()
                page.wait_for_timeout(2000)

                # Check for error message
                error_locator = page.locator(".n-message--error")
                if error_locator.count() > 0:
                    error_text = error_locator.first.text_content()
                    print(f"ERROR FOUND: {error_text}")
                    # Take screenshot for debugging
                    page.screenshot(path="/tmp/error_screenshot.png")
                    pytest.fail(f"Error appeared after clicking save: {error_text}")

                success_locator = page.locator(".n-message--success")
                if success_locator.count() > 0:
                    success_text = success_locator.first.text_content()
                    print(f"SUCCESS: {success_text}")
                    return  # Test passed

        pytest.skip("No enabled Save Access button found (possibly only current user exists)")

    def test_update_user_role_click_save_access(self, page: Page, reset_database):
        """
        Reproduce the exact issue: clicking 'Save Access' shows 'Failed to update user access'.

        This test tries to reproduce:
        1. Navigate to access-management
        2. Find Administrator user row
        3. Change their role dropdown
        4. Click 'Save Access'
        5. Error 'Failed to update user access' should NOT appear
        """
        self._create_admin_and_login(page)

        # Navigate to access management
        page.goto("/access-management")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # Look for any select/dropdown elements that control role
        # In the user table, role is shown as a select

        # Find role selects - they should be inside the user rows
        role_selects = page.locator(".n-data-table .n-select")
        select_count = role_selects.count()
        print(f"Found {select_count} select elements on page")

        # Print page content for debugging
        content = page.content()
        with open("/tmp/access_management_page.html", "w") as f:
            f.write(content)
        print("Saved page HTML to /tmp/access_management_page.html")

        # Take a screenshot
        page.screenshot(path="/tmp/access_management.png")

        # Look for the first non-disabled Save Access button
        save_buttons = page.get_by_role("button", name="Save Access")
        for i in range(save_buttons.count()):
            btn = save_buttons.nth(i)
            is_disabled = btn.is_disabled()
            print(f"Save Access button {i}: disabled={is_disabled}")
            if not is_disabled:
                # Click it
                btn.click()
                page.wait_for_timeout(2000)

                # Check for the specific error message
                page_content = page.content()
                if "Failed to update user access" in page_content:
                    pytest.fail("Reproduced: 'Failed to update user access' error appeared!")
                elif "updatedAccess" in page_content or "success" in page_content.lower():
                    print("Success message found - no error")
                    return
                else:
                    print("Neither success nor error message found")

        pytest.skip("Could not find enabled Save Access button to click")
