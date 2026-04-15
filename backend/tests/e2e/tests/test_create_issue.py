"""
Create Issue E2E Tests

Tests for the Create Issue page (/issues/create) including:
- Page loads and layout
- All form fields present (project, title, description, branches)
- Form validation (submit without required fields)
- Project selection triggers branch loading
- Successful form submission → redirect to issue view
- /create-task redirect to /issues/create
"""

import re

import pytest
from playwright.sync_api import Page, expect
from conftest import api_get_first_project, _get_cookies


# ---------------------------------------------------------------------------
# 1. Page layout (read-only, class_page)
# ---------------------------------------------------------------------------

@pytest.mark.create_issue
class TestCreateIssuePage:
    """Tests for create issue page layout."""

    def test_create_issue_page_loads(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        expect(class_page.get_by_test_id("create-issue-page")).to_be_visible()

    def test_create_issue_header_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        expect(class_page.get_by_test_id("create-issue-header")).to_be_visible()

    def test_create_issue_form_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        expect(class_page.get_by_test_id("create-issue-form")).to_be_visible()

    def test_project_select_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        # NSelect renders as .n-base-selection with placeholder as text content
        project_sel = class_page.locator(".n-base-selection").filter(has_text="Select a project")
        expect(project_sel).to_be_visible()

    def test_title_input_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        expect(class_page.get_by_placeholder("Title")).to_be_visible()

    def test_description_input_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        # Description uses VariableEditor (CodeMirror), not a plain input
        editor = class_page.locator(".variable-editor .cm-editor")
        expect(editor).to_be_visible()

    def test_base_branch_select_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        base_sel = class_page.locator(".n-base-selection").filter(has_text="Select base branch")
        expect(base_sel).to_be_visible()

    def test_target_branch_select_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        # Target branch requires: 1) project selected (to enable MR toggle), 2) MR toggle ON
        # Select a project first
        project_sel = class_page.locator(".n-base-selection").first
        project_sel.click()
        class_page.locator(".n-base-select-option").first.wait_for(state="visible", timeout=5000)
        class_page.locator(".n-base-select-option").first.click()
        class_page.wait_for_timeout(1000)
        # Enable MR toggle
        mr_switch = class_page.locator(".n-switch")
        mr_switch.click()
        class_page.wait_for_timeout(1500)
        # Look for the target branch form item (v-if condition should now be met)
        # The select will be inside a form-item with label "Target Branch"
        target_form_item = class_page.locator("label").filter(has_text=re.compile(r"Target\s*Branch", re.IGNORECASE))
        expect(target_form_item).to_be_visible(timeout=10000)

    def test_submit_button_visible(self, class_page: Page):
        class_page.goto("/issues/create")
        class_page.wait_for_load_state("networkidle")
        expect(class_page.get_by_test_id("create-issue-submit")).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Route redirect
# ---------------------------------------------------------------------------

@pytest.mark.create_issue
class TestCreateTaskRedirect:
    """Test that old /create-task route redirects to /issues/create."""

    def test_create_task_redirects_to_create_issue(self, class_page: Page):
        class_page.goto("/create-task")
        class_page.wait_for_url("**/issues/create", timeout=5000)
        assert "/issues/create" in class_page.url


# ---------------------------------------------------------------------------
# 3. Form validation (logged_in_page)
# ---------------------------------------------------------------------------

@pytest.mark.create_issue
class TestCreateIssueValidation:
    """Tests for form validation."""

    def test_submit_without_fields_stays_on_page(self, logged_in_page: Page):
        """Clicking submit without filling anything should stay on the create page."""
        logged_in_page.goto("/issues/create")
        logged_in_page.wait_for_load_state("networkidle")

        logged_in_page.get_by_test_id("create-issue-submit").click()
        logged_in_page.wait_for_timeout(500)

        # Should still be on create page (validation prevents submission)
        assert "/issues/create" in logged_in_page.url


# ---------------------------------------------------------------------------
# 4. Project selection triggers branch loading
# ---------------------------------------------------------------------------

@pytest.mark.create_issue
class TestCreateIssueBranchLoading:
    """Test that selecting a project loads branches."""

    def test_selecting_project_loads_branches(self, logged_in_page: Page, backend_url):
        """After selecting a project, branch selects should become populated."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)

        logged_in_page.goto("/issues/create")
        logged_in_page.wait_for_load_state("networkidle")

        # Click the project NSelect (rendered as .n-base-selection)
        project_sel = logged_in_page.locator(".n-base-selection").filter(has_text="Select a project")
        project_sel.click()
        logged_in_page.wait_for_timeout(500)
        logged_in_page.locator(".n-base-select-option").first.click()
        logged_in_page.wait_for_timeout(1500)

        # After project selection, base branch may auto-fill with default branch.
        # Click the second .n-base-selection (base branch) to check for options.
        form = logged_in_page.get_by_test_id("create-issue-form")
        base_sel = form.locator(".n-base-selection").nth(1)
        base_sel.click()
        logged_in_page.wait_for_timeout(500)

        options = logged_in_page.locator(".n-base-select-option")
        assert options.count() >= 1, "No branch options loaded after project selection"


# ---------------------------------------------------------------------------
# 5. Successful form submission (logged_in_page)
# ---------------------------------------------------------------------------

@pytest.mark.create_issue
class TestCreateIssueSubmission:
    """Tests for successful issue creation via form."""

    def test_submit_valid_form_redirects_to_issue_view(self, logged_in_page: Page, backend_url):
        """Filling all required fields and submitting should redirect to issue view."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)

        logged_in_page.goto("/issues/create")
        logged_in_page.wait_for_load_state("networkidle")

        # Select project (NSelect rendered as .n-base-selection)
        form = logged_in_page.get_by_test_id("create-issue-form")
        project_sel = form.locator(".n-base-selection").first
        project_sel.click()
        logged_in_page.wait_for_timeout(500)
        logged_in_page.locator(".n-base-select-option").first.click()
        logged_in_page.wait_for_timeout(500)

        # Fill title
        logged_in_page.get_by_placeholder("Title").fill("E2E Test Issue Submission")

        # Fill description via CodeMirror (VariableEditor)
        editor = logged_in_page.locator(".variable-editor .cm-content")
        editor.click()
        editor.fill("Automated E2E test issue description")

        # Submit
        logged_in_page.get_by_test_id("create-issue-submit").click()

        # Should redirect to /issues/:id (numeric ID, not /issues/create)
        logged_in_page.wait_for_url(re.compile(r"/issues/\d+$"), timeout=10000)
        assert re.search(r"/issues/\d+$", logged_in_page.url)
