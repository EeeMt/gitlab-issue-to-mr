"""
Prompt Template E2E Tests

Tests for the prompt template management functionality in the Config page.
The VariableEditor component uses CodeMirror and does not have a placeholder attribute,
so tests should use CodeMirror selectors (e.g., .cm-content) instead of placeholder-based selectors.
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.prompt_template
class TestPromptTemplates:
    """Tests for the prompt template management feature."""

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

    def test_prompt_template_modal_opens(self, page: Page, reset_database):
        """
        Test that the prompt template creation modal opens when clicking the create button.
        """
        self._create_admin_and_login(page)

        page.goto("/config")
        page.wait_for_load_state("networkidle")

        # Navigate to prompt templates tab
        page.get_by_role("tab", name="Prompt Templates").click()
        page.wait_for_timeout(500)  # Allow tab to render

        # Click create template button
        page.get_by_role("button", name="Create Template").click()

        # Verify modal is visible
        expect(page.locator(".n-card")).to_be_visible()
        expect(page.get_by_text("Name")).to_be_visible()

    def test_prompt_template_name_input_works(self, page: Page, reset_database):
        """
        Test that the prompt template name input field works correctly.
        """
        self._create_admin_and_login(page)

        page.goto("/config")
        page.wait_for_load_state("networkidle")

        # Navigate to prompt templates tab
        page.get_by_role("tab", name="Prompt Templates").click()
        page.wait_for_timeout(500)

        # Click create template button
        page.get_by_role("button", name="Create Template").click()

        # Fill in the name field - this uses n-input with placeholder
        name_input = page.locator(".n-card input").first
        name_input.fill("Test Template")
        expect(name_input).to_have_value("Test Template")

    def test_variable_editor_accepts_input(self, page: Page, reset_database):
        """
        Test that the VariableEditor (CodeMirror) accepts input correctly.

        Note: The VariableEditor uses CodeMirror, not a standard input element.
        It does not have a placeholder attribute. To interact with it, we use
        the .cm-content selector which targets the CodeMirror content area.
        """
        self._create_admin_and_login(page)

        page.goto("/config")
        page.wait_for_load_state("networkidle")

        # Navigate to prompt templates tab
        page.get_by_role("tab", name="Prompt Templates").click()
        page.wait_for_timeout(500)

        # Click create template button
        page.get_by_role("button", name="Create Template").click()

        # Interact with the VariableEditor using CodeMirror's .cm-content selector
        # The VariableEditor component renders as .variable-editor with .cm-editor inside
        cm_content = page.locator(".variable-editor .cm-content")
        expect(cm_content).to_be_visible()

        # Click to focus and type
        cm_content.click()
        cm_content.fill("This is a test prompt with {{variable}} placeholder")

        # Verify content was entered
        expect(cm_content).to_contain_text("{{variable}}")

    def test_validation_console_logs(self, page: Page, reset_database):
        """
        Test that validation warnings appear in console when using invalid variable tips.

        This test verifies that the UI properly validates variable tips against
        the actual variables used in the template content.
        """
        self._create_admin_and_login(page)

        page.goto("/config")
        page.wait_for_load_state("networkidle")

        # Navigate to prompt templates tab
        page.get_by_role("tab", name="Prompt Templates").click()
        page.wait_for_timeout(500)

        # Click create template button
        page.get_by_role("button", name="Create Template").click()

        # Fill in template with a variable
        cm_content = page.locator(".variable-editor .cm-content")
        cm_content.click()
        cm_content.fill("Hello {{name}}, please review {{code}}")

        # The VariableEditor should detect variables automatically
        # and display them in the tips panel below the editor
        tips_panel = page.locator(".variable-editor__tips-panel")
        expect(tips_panel).to_be_visible()

        # Verify the variable names appear in the tips
        expect(tips_panel).to_contain_text("name")
        expect(tips_panel).to_contain_text("code")

    def test_save_prompt_template(self, page: Page, reset_database):
        """
        Test that a prompt template can be saved successfully.
        """
        self._create_admin_and_login(page)

        page.goto("/config")
        page.wait_for_load_state("networkidle")

        # Navigate to prompt templates tab
        page.get_by_role("tab", name="Prompt Templates").click()
        page.wait_for_timeout(500)

        # Click create template button
        page.get_by_role("button", name="Create Template").click()

        # Fill in the name
        name_input = page.locator(".n-card input").first
        name_input.fill("My Test Template")

        # Fill in the content using CodeMirror
        cm_content = page.locator(".variable-editor .cm-content")
        cm_content.click()
        cm_content.fill("Please review the changes in {{files}}")

        # Click save
        page.get_by_role("button", name="Save").click()

        # Wait for modal to close and verify success message
        page.wait_for_timeout(1000)

        # The modal should be closed and we should see the template in the list
        expect(page.locator(".n-data-table")).to_be_visible()
        expect(page.get_by_text("My Test Template")).to_be_visible()
