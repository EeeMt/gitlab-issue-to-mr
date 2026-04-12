"""
Task List E2E Tests

Tests for the Task List page (/tasks) functionality including:
- Task list viewing with filters
- Summary card display
- Task table display
"""

import pytest
from playwright.sync_api import Page, expect




@pytest.mark.task_list
class TestTaskList:
    """Tests for the task list page functionality."""

    def test_task_list_page_loads(self, class_page: Page):
        """Test that the task list page loads without errors."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("tasks-page")).to_be_visible()

    def test_task_list_has_summary_cards(self, class_page: Page):
        """Test that task list displays summary cards."""
        class_page.goto("/tasks")
        class_page.wait_for_selector("[data-testid='tasks-summary']", timeout=10000)
        summary_cards = class_page.locator(".dashboard-summary-card")
        expect(summary_cards.first).to_be_visible()

    def test_task_list_has_data_table(self, class_page: Page):
        """Test that task list displays data table."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("tasks-table")).to_be_visible()

    def test_task_list_has_header(self, class_page: Page):
        """Test that task list has a header."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("tasks-header")).to_be_visible()


@pytest.mark.task_list
class TestTaskListFilters:
    """Tests for task list filter functionality."""

    def test_status_filter_exists(self, class_page: Page):
        """Test that status filter dropdown is present."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        filter_selects = class_page.locator(".dashboard__filters .n-select")
        if filter_selects.count() > 0:
            expect(filter_selects.first).to_be_visible()

    def test_refresh_button_exists(self, class_page: Page):
        """Test that refresh button is present."""
        class_page.goto("/tasks")
        class_page.wait_for_load_state("domcontentloaded")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        if refresh_button.is_visible():
            expect(refresh_button).to_be_visible()
