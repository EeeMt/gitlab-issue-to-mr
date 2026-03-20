"""
Debug script to investigate Bootstrap page button issue.
"""
import pytest
from playwright.sync_api import Page


def test_debug_bootstrap_page(page: Page):
    """Debug the Bootstrap page to understand button issue."""
    page.goto("/bootstrap")
    page.wait_for_load_state("networkidle")

    # Get page title
    print(f"Page URL: {page.url}")
    print(f"Page title: {page.title()}")

    # Check for console errors
    console_logs = []
    page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
    page.reload()
    page.wait_for_load_state("networkidle")

    # Print all console messages
    print("\n=== Console messages ===")
    for log in console_logs:
        print(log)

    # Check page HTML structure
    print("\n=== Page content ===")
    content = page.content()
    print(f"HTML length: {len(content)}")

    # Check for the form
    form = page.locator("form")
    print(f"Form found: {form.count()}")

    # Check for the button
    button = page.get_by_role("button", name="Create Admin")
    print(f"Button found: {button.count()}")

    if button.count() > 0:
        print(f"Button visible: {button.is_visible()}")
        print(f"Button enabled: {button.is_enabled()}")

    # Check for any error overlay or loading state
    loading = page.locator(".n-spin")
    print(f"Loading spinner: {loading.count()}")

    # Take screenshot for debugging
    page.screenshot(path="/tmp/bootstrap_debug.png")
    print("\nScreenshot saved to /tmp/bootstrap_debug.png")


def test_debug_form_submission(page: Page):
    """Debug form submission to see what happens."""
    page.goto("/bootstrap")
    page.wait_for_load_state("networkidle")

    # Wait a bit for Vue to initialize
    page.wait_for_timeout(2000)

    # Try to find the form
    form = page.locator("form.bootstrap-form")
    print(f"\nForm .bootstrap-form found: {form.count()}")

    # Try to find input fields by placeholder
    username_input = page.locator("input[placeholder*='Username' i], input[autocomplete='username']")
    print(f"Username input found: {username_input.count()}")

    # Try to find the button
    button = page.locator("button:has-text('Create Admin'), button:has-text('Create Administrator')")
    print(f"Create Admin button found: {button.count()}")

    if button.count() > 0:
        btn = button.first
        print(f"Button text: {btn.text_content()}")
        print(f"Button disabled: {btn.is_disabled()}")

        # Check if there's a loading state
        parent = btn.locator("xpath=..")
        print(f"Button parent classes: {parent.get_attribute('class')}")

        # Try clicking
        print("\n=== Clicking button ===")
        with page.expect_request(lambda r: "/api/" in r.url):
            btn.click()
        page.wait_for_timeout(2000)

        print(f"Page URL after click: {page.url}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
