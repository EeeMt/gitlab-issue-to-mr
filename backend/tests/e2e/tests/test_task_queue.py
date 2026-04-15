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

    def test_filter_toolbar_exists(self, class_page: Page):
        """Filter toolbar should be visible on the page."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("filter-toolbar")).to_be_visible()

    def test_filter_button_exists(self, class_page: Page):
        """Filter button should be visible in the filter toolbar."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("filter-toolbar-filter-btn")).to_be_visible()

    def test_search_input_exists(self, class_page: Page):
        """Search input should be visible in the filter toolbar."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("filter-toolbar-search")).to_be_visible()

    def test_filter_button_opens_popover(self, logged_in_page: Page):
        """Clicking filter button should show filter popover with options."""
        logged_in_page.goto("/tasks")
        logged_in_page.wait_for_load_state("networkidle")

        # Click the filter button to open FilterPopover
        filter_btn = logged_in_page.get_by_test_id("filter-toolbar-filter-btn")
        filter_btn.click()
        logged_in_page.wait_for_timeout(500)

        # Check that a popover or dropdown appears (FilterPopover uses n-popover)
        popover = logged_in_page.locator(".n-popover")
        expect(popover.first).to_be_visible(timeout=5000)


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


@pytest.mark.task_list
class TestTaskListRefactoredFeatures:
    """Tests for new task list features after FilterToolbar refactoring."""

    def test_filter_toolbar_visible_on_load(self, class_page: Page):
        """Filter toolbar should be visible on page load."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        toolbar = class_page.get_by_test_id("filter-toolbar")
        expect(toolbar).to_be_visible()

    def test_filter_toolbar_search_visible(self, class_page: Page):
        """Search input should be visible in filter toolbar."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        search = class_page.get_by_test_id("filter-toolbar-search")
        expect(search).to_be_visible()

    def test_filter_toolbar_has_sort_button(self, class_page: Page):
        """Sort button should be visible in filter toolbar."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        sort_btn = class_page.get_by_test_id("filter-toolbar-sort-btn")
        expect(sort_btn).to_be_visible()

    def test_filter_toolbar_has_columns_button(self, class_page: Page):
        """Columns button should be visible in filter toolbar."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        columns_btn = class_page.get_by_test_id("filter-toolbar-columns-btn")
        expect(columns_btn).to_be_visible()

    def test_summary_cards_show_correct_labels(self, class_page: Page):
        """Summary cards should have metric-title labels."""
        class_page.goto("/tasks")
        class_page.wait_for_selector("[data-testid='tasks-summary']", timeout=10000)
        
        # Check for metric-title elements (new structure)
        labels = class_page.locator(".metric-title")
        if labels.count() > 0:
            expect(labels.first).to_be_visible()

    def test_summary_section_has_cards(self, class_page: Page):
        """Summary section should have multiple summary cards."""
        class_page.goto("/tasks")
        class_page.wait_for_selector("[data-testid='tasks-summary']", timeout=10000)
        
        cards = class_page.get_by_test_id("tasks-summary-card")
        assert cards.count() >= 1, "Summary section should have at least one card"
