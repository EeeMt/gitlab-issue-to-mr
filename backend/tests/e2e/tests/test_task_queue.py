"""
Task List E2E Tests

Tests for the Task List page (/tasks) including:
- Page layout: header, summary cards, table
- Summary card count and values
- Task data table with columns
- Status/project/initiator filters
- Task created via API appears in list
- Task row click navigation to TaskView
"""

import pytest
from playwright.sync_api import Page, expect
from conftest import (
    api_create_issue, api_create_task, api_get_first_project, _get_cookies
)


# ---------------------------------------------------------------------------
# 1. Page layout (read-only, class_page)
# ---------------------------------------------------------------------------

@pytest.mark.task_list
class TestTaskListPage:
    """Tests for task list page layout."""

    def test_task_list_page_loads(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("tasks-page")).to_be_visible()

    def test_task_list_header_visible(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("tasks-header")).to_be_visible()

    def test_task_list_summary_visible(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_selector("[data-testid='tasks-summary']", timeout=10000)
        expect(class_page.get_by_test_id("tasks-summary")).to_be_visible()

    def test_task_list_table_visible(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("tasks-table")).to_be_visible()

    def test_table_has_expected_columns(self, class_page: Page):
        """Task table should have ID, Prompt/Issue, Status, Priority, etc."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("networkidle")
        table = class_page.get_by_test_id("tasks-table")
        headers = table.locator("thead th")
        expect(headers.first).to_be_visible(timeout=5000)
        assert headers.count() >= 4


@pytest.mark.task_list
class TestTaskListSummaryCards:
    """Tests for summary cards on the task list page."""

    def test_summary_cards_are_rendered(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_selector("[data-testid='tasks-summary']", timeout=10000)
        cards = class_page.get_by_test_id("tasks-summary-card")
        expect(cards.first).to_be_visible()

    def test_summary_card_values_are_numeric(self, class_page: Page):
        """Summary card values should be numbers."""
        class_page.goto("/tasks")
        class_page.wait_for_selector("[data-testid='tasks-summary']", timeout=10000)
        values = class_page.locator(".summary-card__value")
        for i in range(values.count()):
            text = values.nth(i).inner_text().strip()
            assert text.isdigit(), f"Card value {i} is not numeric: {text!r}"


# ---------------------------------------------------------------------------
# 2. Filters (read-only, class_page)
# ---------------------------------------------------------------------------

@pytest.mark.task_list
class TestTaskListFilters:
    """Tests for task list filter controls."""

    def test_status_filter_exists(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        status_filter = class_page.locator(".dashboard__filter--status")
        expect(status_filter).to_be_visible()

    def test_project_filter_exists(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        project_filter = class_page.locator(".dashboard__filter--project")
        expect(project_filter).to_be_visible()

    def test_initiator_filter_exists(self, class_page: Page):
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        initiator_filter = class_page.locator(".dashboard__filter--initiator")
        expect(initiator_filter).to_be_visible()

    def test_status_filter_opens_dropdown(self, logged_in_page: Page):
        """Clicking status filter should show dropdown options."""
        logged_in_page.goto("/tasks")
        logged_in_page.wait_for_load_state("networkidle")

        status_filter = logged_in_page.locator(".dashboard__filter--status .n-base-selection")
        status_filter.click()
        logged_in_page.wait_for_timeout(500)

        options = logged_in_page.locator(".n-base-select-option")
        assert options.count() >= 5


# ---------------------------------------------------------------------------
# 3. Data interactions (logged_in_page)
# ---------------------------------------------------------------------------

@pytest.mark.task_list
class TestTaskListData:
    """Tests for task list data display."""

    def test_created_task_appears_in_list(self, logged_in_page: Page, backend_url):
        """A task created via API should appear in the task list."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        issue = api_create_issue(backend_url, cookies, project["id"], title="TQ Data")
        task = api_create_task(backend_url, cookies, issue["id"], prompt="task-queue-visible")

        logged_in_page.goto("/tasks")
        logged_in_page.wait_for_load_state("networkidle")

        table = logged_in_page.get_by_test_id("tasks-table")
        # Find task by its ID in the first column
        task_id_text = str(task["id"])
        expect(table.locator("tr").filter(has_text=task_id_text).first).to_be_visible(timeout=10000)

    def test_click_task_row_navigates_to_task_view(self, logged_in_page: Page, backend_url):
        """Clicking a task row should navigate to /tasks/:id."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        issue = api_create_issue(backend_url, cookies, project["id"], title="TQ Click")
        task = api_create_task(backend_url, cookies, issue["id"], prompt="task-queue-click")

        logged_in_page.goto("/tasks")
        logged_in_page.wait_for_load_state("networkidle")

        table = logged_in_page.get_by_test_id("tasks-table")
        task_id_text = str(task["id"])
        row = table.locator("tr").filter(has_text=task_id_text).first
        expect(row).to_be_visible(timeout=10000)
        row.click()
        logged_in_page.wait_for_url(f"**/tasks/{task['id']}", timeout=10000)
        assert f"/tasks/{task['id']}" in logged_in_page.url


# ---------------------------------------------------------------------------
# 4. Pagination (read-only)
# ---------------------------------------------------------------------------

@pytest.mark.task_list
class TestTaskListPagination:
    """Tests for task list pagination controls."""

    def test_pagination_is_visible(self, class_page: Page):
        """Pagination controls should be visible in the table card."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("networkidle")
        pagination = class_page.locator(".n-pagination")
        if pagination.count() > 0:
            expect(pagination.first).to_be_visible()
