"""
Prompt Template E2E Tests

Tests for the prompt template management functionality in the Config logged_in_page.
The VariableEditor component uses CodeMirror and does not have a placeholder attribute,
so tests should use CodeMirror selectors (e.g., .cm-content) instead of placeholder-based selectors.
"""

import os

import pytest
from playwright.sync_api import Page, expect

# These tests modify shared config state and require serial execution.
# They are skipped when running with pytest-xdist (-n flag).
# Run them separately with:
#   pytest tests/e2e/tests/test_bootstrap.py tests/e2e/tests/test_prompt_template.py tests/e2e/tests/test_access_management.py
pytestmark = pytest.mark.skipif(
    bool(os.environ.get("PYTEST_XDIST_WORKER")),
    reason="Requires serial execution (modifies shared DB state)",
)



@pytest.mark.prompt_template
class TestPromptTemplates:
    """Tests for the prompt template management feature."""

    def open_prompt_templates(self, page: Page):
        page.goto("/config?tab=prompt-templates")
        # Use networkidle to ensure the Vue app has fully initialized and the
        # config API call has completed before asserting on tab panel content.
        page.wait_for_load_state("networkidle")
        # n-button does not forward data-testid to the DOM; use role+name selector instead
        expect(page.get_by_role("button", name="Create Template")).to_be_visible()

    def create_template(self, page: Page, name: str, content: str):
        page.get_by_role("button", name="Create Template").click()
        # n-input does not forward data-testid; target the underlying input element
        page.locator(".prompt-template-editor input").first.fill(name)
        cm_content = page.locator(".variable-editor .cm-content")
        cm_content.click()
        cm_content.fill(content)
        page.locator(".prompt-template-editor__actions").get_by_role("button", name="Save").click()
        # Wait for the editor div to be removed from the DOM (save succeeded)
        page.wait_for_selector(".prompt-template-editor", state="detached", timeout=5000)

    def test_prompt_template_editor_opens_inline(self, logged_in_page: Page, reset_database):
        """Test that the prompt template creation editor opens inline when clicking create."""
        self.open_prompt_templates(logged_in_page)
        create_button = logged_in_page.get_by_role("button", name="Create Template")
        expect(create_button).to_be_visible()
        create_button.click()
        editor = logged_in_page.locator(".prompt-template-editor")
        expect(editor).to_be_visible()
        name_input = logged_in_page.locator(".prompt-template-editor input").first
        expect(name_input).to_be_visible()

    def test_prompt_template_name_input_works(self, logged_in_page: Page, reset_database):
        """Test that the prompt template name input field works correctly."""
        self.open_prompt_templates(logged_in_page)
        logged_in_page.get_by_role("button", name="Create Template").click()
        name_input = logged_in_page.locator(".prompt-template-editor input").first
        name_input.fill("Test Template")
        expect(name_input).to_have_value("Test Template")

    def test_variable_editor_accepts_input(self, logged_in_page: Page, reset_database):
        """Test that the VariableEditor (CodeMirror) accepts input correctly."""
        self.open_prompt_templates(logged_in_page)
        logged_in_page.get_by_role("button", name="Create Template").click()
        cm_content = logged_in_page.locator(".variable-editor .cm-content")
        expect(cm_content).to_be_visible()
        cm_content.click()
        cm_content.fill("This is a test prompt with {{variable}} placeholder")
        expect(cm_content).to_contain_text("{{variable}}")

    def test_first_character_input_has_no_codemirror_crash(self, logged_in_page: Page, reset_database):
        """Test that the first typed character does not trigger a CodeMirror plugin crash."""
        console_errors = []
        page_errors = []

        logged_in_page.on(
            "console",
            lambda msg: console_errors.append(msg.text)
            if msg.type == "error"
            else None,
        )
        logged_in_page.on("pageerror", lambda error: page_errors.append(str(error)))

        self.open_prompt_templates(logged_in_page)
        logged_in_page.get_by_role("button", name="Create Template").click()

        cm_content = logged_in_page.locator(".variable-editor .cm-content")
        expect(cm_content).to_be_visible()
        cm_content.click()
        logged_in_page.keyboard.type("a")
        logged_in_page.wait_for_timeout(500)

        joined_errors = "\n".join(console_errors + page_errors)
        assert "CodeMirror plugin crashed" not in joined_errors
        assert "Position 1 is out of range for changeset of length 0" not in joined_errors

    def test_validation_console_logs(self, logged_in_page: Page, reset_database):
        """Test that validation warnings appear in console when using invalid variable tips."""
        self.open_prompt_templates(logged_in_page)
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
        self.open_prompt_templates(logged_in_page)
        self.create_template(logged_in_page, "My Test Template", "Please review the changes in {{files}}")
        expect(logged_in_page.locator(".n-data-table")).to_be_visible()
        expect(logged_in_page.get_by_text("My Test Template").first).to_be_visible()

    def test_edit_prompt_template(self, logged_in_page: Page, reset_database):
        """Test that an existing prompt template can be edited."""
        self.open_prompt_templates(logged_in_page)
        self.create_template(logged_in_page, "Editable Template", "Original {{files}}")

        edit_button = logged_in_page.locator(".n-data-table").get_by_role("button", name="Edit").first
        expect(edit_button).to_be_visible()
        edit_button.click()

        name_input = logged_in_page.locator(".prompt-template-editor input").first
        expect(name_input).to_have_value("Editable Template")
        name_input.fill("Edited Template")
        logged_in_page.locator(".prompt-template-editor__actions").get_by_role("button", name="Save").click()
        # Wait for the editor to close then assert updated name is in the list
        logged_in_page.wait_for_selector(".prompt-template-editor", state="detached", timeout=5000)

        expect(logged_in_page.get_by_text("Edited Template").first).to_be_visible()

    def test_delete_prompt_template(self, logged_in_page: Page, reset_database):
        """Test that an existing prompt template can be deleted after confirmation."""
        self.open_prompt_templates(logged_in_page)
        self.create_template(logged_in_page, "Disposable Template", "Disposable {{files}}")

        delete_button = logged_in_page.locator(".n-data-table").get_by_role("button", name="Delete").first
        expect(delete_button).to_be_visible()
        delete_button.click()

        # Popconfirm renders in a body-level portal — target the positive action button directly
        confirm_button = logged_in_page.locator(".n-popover").get_by_role("button", name="Delete")
        expect(confirm_button).to_be_visible(timeout=5000)
        confirm_button.click()
        # Wait for the deleted item to disappear from the list
        logged_in_page.get_by_text("Disposable Template").wait_for(state="detached", timeout=5000)

        expect(logged_in_page.get_by_text("Disposable Template")).to_have_count(0)
