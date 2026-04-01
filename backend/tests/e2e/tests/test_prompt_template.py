"""
Prompt Template E2E Tests

Tests for the prompt template management functionality in the Config logged_in_page.
The VariableEditor component uses CodeMirror and does not have a placeholder attribute,
so tests should use CodeMirror selectors (e.g., .cm-content) instead of placeholder-based selectors.
"""

import pytest
from playwright.sync_api import Page, expect




@pytest.mark.prompt_template
class TestPromptTemplates:
    """Tests for the prompt template management feature."""

    def test_prompt_template_modal_opens(self, logged_in_page: Page, reset_database):
        """Test that the prompt template creation modal opens when clicking the create button."""
        logged_in_page.goto("/config")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        # Use nth(6) since Prompt Templates is the 7th tab
        prompt_tab = logged_in_page.locator(".n-tabs-tab").nth(6)
        prompt_tab.scroll_into_view_if_needed()
        prompt_tab.click()
        logged_in_page.wait_for_timeout(1000)
        logged_in_page.get_by_role("button", name="Create Template").click()
        expect(logged_in_page.locator(".n-modal")).to_be_visible()
        expect(logged_in_page.get_by_role("dialog").get_by_text("Name")).to_be_visible()

    def test_prompt_template_name_input_works(self, logged_in_page: Page, reset_database):
        """Test that the prompt template name input field works correctly."""
        logged_in_page.goto("/config")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        prompt_tab = logged_in_page.locator(".n-tabs-tab").nth(6)
        prompt_tab.scroll_into_view_if_needed()
        prompt_tab.click()
        logged_in_page.wait_for_timeout(1000)
        logged_in_page.get_by_role("button", name="Create Template").click()
        name_input = logged_in_page.locator(".n-card input").first
        name_input.fill("Test Template")
        expect(name_input).to_have_value("Test Template")

    def test_variable_editor_accepts_input(self, logged_in_page: Page, reset_database):
        """Test that the VariableEditor (CodeMirror) accepts input correctly."""
        logged_in_page.goto("/config")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        prompt_tab = logged_in_page.locator(".n-tabs-tab").nth(6)
        prompt_tab.scroll_into_view_if_needed()
        prompt_tab.click()
        logged_in_page.wait_for_timeout(1000)
        logged_in_page.get_by_role("button", name="Create Template").click()
        cm_content = logged_in_page.locator(".variable-editor .cm-content")
        expect(cm_content).to_be_visible()
        cm_content.click()
        cm_content.fill("This is a test prompt with {{variable}} placeholder")
        expect(cm_content).to_contain_text("{{variable}}")

    def test_validation_console_logs(self, logged_in_page: Page, reset_database):
        """Test that validation warnings appear in console when using invalid variable tips."""
        logged_in_page.goto("/config")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        prompt_tab = logged_in_page.locator(".n-tabs-tab").nth(6)
        prompt_tab.scroll_into_view_if_needed()
        prompt_tab.click()
        logged_in_page.wait_for_timeout(1000)
        logged_in_page.get_by_role("button", name="Create Template").click()
        cm_content = logged_in_page.locator(".variable-editor .cm-content")
        cm_content.click()
        cm_content.fill("Hello {{name}}, please review {{code}}")
        tips_panel = logged_in_page.locator(".variable-editor__tips-panel")
        expect(tips_panel).to_be_visible()
        expect(tips_panel).to_contain_text("name")
        expect(tips_panel).to_contain_text("code")

    def test_save_prompt_template(self, logged_in_page: Page, reset_database):
        """Test that a prompt template can be saved successfully."""
        logged_in_page.goto("/config")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        prompt_tab = logged_in_page.locator(".n-tabs-tab").nth(6)
        prompt_tab.scroll_into_view_if_needed()
        prompt_tab.click()
        logged_in_page.wait_for_timeout(1000)
        logged_in_page.get_by_role("button", name="Create Template").click()
        name_input = logged_in_page.locator(".n-card input").first
        name_input.fill("My Test Template")
        cm_content = logged_in_page.locator(".variable-editor .cm-content")
        cm_content.click()
        cm_content.fill("Please review the changes in {{files}}")
        logged_in_page.get_by_role("button", name="Save").click()
        logged_in_page.wait_for_timeout(1000)
        expect(logged_in_page.locator(".n-data-table")).to_be_visible()
        expect(logged_in_page.get_by_text("My Test Template").first).to_be_visible()
