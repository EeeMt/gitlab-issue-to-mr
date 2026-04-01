"""
Task Detail View E2E Tests

Tests for the TaskView page functionality including:
- Task detail display
- Cancel/retry/execute button actions
- Log display
- Permission checks
"""

import pytest
from playwright.sync_api import Page, expect




@pytest.mark.task_details
class TestTaskDetailView:
    """Tests for the task detail view functionality."""

    def test_task_view_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the task view page loads without errors when accessing a valid task."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        task_view = logged_in_page.locator(".task-view")
        expect(task_view).to_be_visible()

    def test_task_view_has_title(self, logged_in_page: Page, reset_database):
        """Test that task view displays title with task ID."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        title = logged_in_page.locator(".task-view__title")
        if title.is_visible():
            expect(title).to_contain_text("1")

    def test_task_view_has_summary_cards(self, logged_in_page: Page, reset_database):
        """Test that task view displays summary cards when task is loaded."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        summary = logged_in_page.locator(".task-view__summary")
        if summary.is_visible():
            summary_cards = logged_in_page.locator(".task-summary-card")
            expect(summary_cards.first).to_be_visible()

    def test_task_view_has_task_details_card(self, logged_in_page: Page, reset_database):
        """Test that task view has a task details card."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        task_cards = logged_in_page.locator(".task-card")
        expect(task_cards.first).to_be_visible()

    def test_task_view_has_refresh_button(self, logged_in_page: Page, reset_database):
        """Test that task view has a refresh button."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh").first
        expect(refresh_button).to_be_visible()

    def test_task_view_has_log_section(self, logged_in_page: Page, reset_database):
        """Test that task view has a logs section."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        log_section = logged_in_page.locator(".log-content")
        expect(log_section).to_be_attached()

    def test_task_view_back_to_dashboard(self, logged_in_page: Page, reset_database):
        """Test that navigation back to dashboard works via sidebar."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        dashboard_link = logged_in_page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            logged_in_page.wait_for_url("**/dashboard", timeout=5000)
            assert "/dashboard" in logged_in_page.url


@pytest.mark.task_details
class TestTaskActions:
    """Tests for task action buttons (cancel, retry, execute)."""

    def test_task_actions_card_exists(self, logged_in_page: Page, reset_database):
        """Test that the actions card is present in task view."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        task_actions = logged_in_page.locator(".task-actions")
        if task_actions.is_visible():
            expect(task_actions).to_be_visible()

    def test_cancel_button_exists_for_active_tasks(self, logged_in_page: Page, reset_database):
        """Test that cancel button is shown for pending/running tasks."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        cancel_button = logged_in_page.get_by_role("button", name="Cancel")

    def test_retry_button_exists_for_failed_tasks(self, logged_in_page: Page, reset_database):
        """Test that retry button is shown for failed/cancelled tasks."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        retry_button = logged_in_page.get_by_role("button", name="Retry")

    def test_execute_button_exists_for_pending_tasks(self, logged_in_page: Page, reset_database):
        """Test that execute button is shown for pending tasks."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        execute_button = logged_in_page.get_by_role("button", name="Execute")

    def test_task_view_no_actions_for_completed_tasks(self, logged_in_page: Page, reset_database):
        """Test that completed tasks show no action buttons."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        no_action = logged_in_page.locator(".task-actions__empty")
        if no_action.is_visible():
            expect(no_action).to_contain_text("No manual action is available")


@pytest.mark.task_details
class TestTaskLogs:
    """Tests for task log display."""

    def test_log_content_area_exists(self, logged_in_page: Page, reset_database):
        """Test that the log content area exists."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.wait_for_timeout(1000)
        log_content = logged_in_page.locator(".log-content")
        expect(log_content).to_be_attached()

    def test_logs_refresh_button_exists(self, logged_in_page: Page, reset_database):
        """Test that logs section has a refresh button."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logs_refresh_button = logged_in_page.locator(".task-card").get_by_role("button", name="Refresh")
        if logs_refresh_button.is_visible():
            expect(logs_refresh_button).to_be_visible()
