"""
Issue View E2E Tests

Tests for the Issue View page (/issues/:id) including:
- Page loads and layout sections
- Metadata card, description card, tasks card
- Create task form (prompt, submit)
- Create task from form → task appears in tasks table
- Edit issue modal (open, modify title, save)
- Close issue (popconfirm → status changes)
- Task click navigation to TaskView
"""

import pytest
from playwright.sync_api import Page, expect
from conftest import (
    api_create_issue, api_create_task, api_get_first_project, _get_cookies
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_issue_id(logged_in_page: Page, backend_url):
    """Create a test issue via API and return its ID."""
    cookies = _get_cookies(logged_in_page)
    project = api_get_first_project(backend_url, cookies)
    issue = api_create_issue(
        backend_url, cookies, project["id"],
        title="E2E IssueView Test Issue",
        description="Test issue for IssueView E2E tests"
    )
    return issue["id"]


@pytest.fixture
def test_issue_with_task(logged_in_page: Page, backend_url):
    """Create a test issue with one task via API. Returns (issue_id, task_id)."""
    cookies = _get_cookies(logged_in_page)
    project = api_get_first_project(backend_url, cookies)
    issue = api_create_issue(
        backend_url, cookies, project["id"],
        title="E2E IssueView WithTask"
    )
    task = api_create_task(
        backend_url, cookies, issue["id"],
        prompt="E2E test task prompt for IssueView"
    )
    return issue["id"], task["id"]


# ---------------------------------------------------------------------------
# 1. Page layout
# ---------------------------------------------------------------------------

@pytest.mark.issue_view
class TestIssueViewPage:
    """Tests for issue view page layout."""

    def test_issue_view_page_loads(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-view-page")).to_be_visible()

    def test_issue_view_header_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-view-header")).to_be_visible()

    def test_metadata_card_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-metadata-card")).to_be_visible()

    def test_description_card_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-description-card")).to_be_visible()

    def test_tasks_card_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-tasks-card")).to_be_visible()

    def test_create_task_card_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-create-task-card")).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Create task form elements
# ---------------------------------------------------------------------------

@pytest.mark.issue_view
class TestIssueViewCreateTaskForm:
    """Tests for the create task form on issue view."""

    def test_task_prompt_input_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("networkidle")
        # Task prompt textarea inside the create task form
        textarea = logged_in_page.get_by_test_id("issue-create-task-card").locator("textarea")
        expect(textarea).to_be_visible()

    def test_create_task_button_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-create-task-button")).to_be_visible()

    def test_edit_button_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-edit-button")).to_be_visible()

    def test_close_button_visible(self, logged_in_page: Page, test_issue_id):
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("issue-close-button")).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Create task from IssueView
# ---------------------------------------------------------------------------

@pytest.mark.issue_view
class TestIssueViewCreateTask:
    """Tests for creating a task from the issue view form."""

    def test_create_task_from_form(self, logged_in_page: Page, test_issue_id):
        """Filling prompt and clicking create should add a task to the tasks card."""
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("networkidle")

        # Fill prompt textarea
        prompt = logged_in_page.get_by_test_id("issue-create-task-card").locator("textarea")
        prompt.fill("E2E form-created task prompt")

        # Click create task
        logged_in_page.get_by_test_id("issue-create-task-button").click()
        logged_in_page.wait_for_timeout(2000)

        # Task should appear in tasks table
        tasks_card = logged_in_page.get_by_test_id("issue-tasks-card")
        expect(tasks_card.get_by_text("E2E form-created task prompt")).to_be_visible(timeout=10000)


# ---------------------------------------------------------------------------
# 4. Issue with existing task — task table and navigation
# ---------------------------------------------------------------------------

@pytest.mark.issue_view
class TestIssueViewTaskTable:
    """Tests for task table on issue view."""

    def test_task_appears_in_tasks_card(self, logged_in_page: Page, test_issue_with_task):
        """Task created via API should be visible in the tasks card."""
        issue_id, task_id = test_issue_with_task
        logged_in_page.goto(f"/issues/{issue_id}")
        logged_in_page.wait_for_load_state("networkidle")

        tasks_card = logged_in_page.get_by_test_id("issue-tasks-card")
        expect(tasks_card.get_by_text("E2E test task prompt for IssueView")).to_be_visible(timeout=10000)

    def test_click_task_navigates_to_task_view(self, logged_in_page: Page, test_issue_with_task):
        """Clicking a task prompt in the table should navigate to /tasks/:id."""
        issue_id, task_id = test_issue_with_task
        logged_in_page.goto(f"/issues/{issue_id}")
        logged_in_page.wait_for_load_state("networkidle")

        tasks_card = logged_in_page.get_by_test_id("issue-tasks-card")
        link = tasks_card.get_by_text("E2E test task prompt for IssueView")
        expect(link).to_be_visible(timeout=10000)
        link.click()
        logged_in_page.wait_for_url(f"**/tasks/{task_id}", timeout=5000)
        assert f"/tasks/{task_id}" in logged_in_page.url


# ---------------------------------------------------------------------------
# 5. Edit issue
# ---------------------------------------------------------------------------

@pytest.mark.issue_view
class TestIssueViewEdit:
    """Tests for editing an issue."""

    def test_edit_button_opens_modal(self, logged_in_page: Page, test_issue_id):
        """Clicking edit button should open a modal."""
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("networkidle")

        logged_in_page.get_by_test_id("issue-edit-button").click()
        logged_in_page.wait_for_timeout(500)

        modal = logged_in_page.locator(".n-modal")
        expect(modal).to_be_visible()

    def test_edit_and_save_updates_title(self, logged_in_page: Page, test_issue_id):
        """Editing the title in the modal and saving should update the displayed title."""
        logged_in_page.goto(f"/issues/{test_issue_id}")
        logged_in_page.wait_for_load_state("networkidle")

        logged_in_page.get_by_test_id("issue-edit-button").click()
        logged_in_page.wait_for_timeout(500)

        modal = logged_in_page.locator(".n-modal")
        title_input = modal.locator("input").first
        title_input.clear()
        title_input.fill("Updated Title by E2E")

        # Click Save or 确定 button
        save_btn = modal.get_by_role("button", name="Save")
        if save_btn.count() == 0:
            save_btn = modal.get_by_role("button", name="确定")
        save_btn.first.click()
        logged_in_page.wait_for_timeout(1000)

        expect(logged_in_page.get_by_text("Updated Title by E2E")).to_be_visible()


# ---------------------------------------------------------------------------
# 6. Close issue
# ---------------------------------------------------------------------------

@pytest.mark.issue_view
class TestIssueViewClose:
    """Tests for closing an issue."""

    def test_close_issue_changes_status(self, logged_in_page: Page, backend_url):
        """Clicking close and confirming popconfirm should change the issue status."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        issue = api_create_issue(
            backend_url, cookies, project["id"],
            title="E2E Close Issue Test"
        )

        logged_in_page.goto(f"/issues/{issue['id']}")
        logged_in_page.wait_for_load_state("networkidle")

        # Click close button (triggers popconfirm)
        close_btn = logged_in_page.get_by_test_id("issue-close-button")
        expect(close_btn).to_be_visible()
        expect(close_btn).to_be_enabled()
        close_btn.click()
        logged_in_page.wait_for_timeout(500)

        # Confirm in popconfirm — look for the positive-action button in the popover
        popover = logged_in_page.locator(".n-popconfirm")
        if popover.count() > 0:
            confirm_btn = popover.locator(".n-button--primary")
            if confirm_btn.count() > 0:
                confirm_btn.first.click()
            else:
                # Fallback: click any button in the popconfirm action area
                popover.locator("button").last.click()
        else:
            # Popconfirm may render differently — try body-level positive button
            logged_in_page.locator(".n-popconfirm__action .n-button--primary-type").first.click()

        logged_in_page.wait_for_timeout(1500)

        # After close, the close button should be disabled
        expect(close_btn).to_be_disabled()
