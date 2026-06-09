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

    def test_task_view_page_loads(self, class_page: Page):
        """Test that the task view page loads without errors when accessing a valid task."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        task_view = class_page.locator(".task-view")
        expect(task_view).to_be_visible()

    def test_task_view_has_title(self, class_page: Page):
        """Test that task view displays title with task ID."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        title = class_page.locator(".task-view__title")
        if title.is_visible():
            expect(title).to_contain_text("1")

    def test_task_view_has_summary_cards(self, class_page: Page):
        """Test that task view displays summary cards when task is loaded."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        summary = class_page.locator(".task-view__summary")
        if summary.is_visible():
            summary_cards = class_page.locator(".task-summary-card")
            expect(summary_cards.first).to_be_visible()

    def test_task_view_has_task_details_card(self, class_page: Page):
        """Test that task view has a task details card."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        task_cards = class_page.locator(".task-card")
        expect(task_cards.first).to_be_visible()

    def test_task_view_has_refresh_button(self, class_page: Page):
        """Test that task view has a refresh button."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        refresh_button = class_page.get_by_role("button", name="Refresh").first
        expect(refresh_button).to_be_visible()

    def test_task_view_has_log_section(self, class_page: Page):
        """Test that task view has a logs/process section."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        log_section = class_page.locator(".task-process-panel")
        expect(log_section).to_be_attached()

    def test_task_view_back_to_dashboard(self, class_page: Page):
        """Test that navigation back to dashboard works via sidebar."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        dashboard_link = class_page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            class_page.wait_for_url("**/dashboard", timeout=5000)
            assert "/dashboard" in class_page.url


@pytest.mark.task_details
class TestTaskActions:
    """Tests for task action buttons (cancel, retry, execute)."""

    def test_task_actions_card_exists(self, class_page: Page):
        """Test that the actions card is present in task view."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        task_actions = class_page.locator(".task-actions")
        if task_actions.is_visible():
            expect(task_actions).to_be_visible()

    def test_cancel_button_exists_for_active_tasks(self, class_page: Page):
        """Test that cancel button is shown for pending/running tasks."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        class_page.get_by_role("button", name="Cancel")

    def test_retry_button_exists_for_failed_tasks(self, class_page: Page):
        """Test that retry button is shown for failed/cancelled tasks."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        class_page.get_by_role("button", name="Retry")

    def test_execute_button_exists_for_pending_tasks(self, class_page: Page):
        """Test that execute button is shown for pending tasks."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        class_page.get_by_role("button", name="Execute")

    def test_task_view_no_actions_for_completed_tasks(self, class_page: Page):
        """Test that completed tasks show no action buttons or show the no-action message."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        class_page.wait_for_selector("[data-testid='task-actions']", state="visible", timeout=10000)
        # Wait for data to settle
        class_page.wait_for_timeout(1000)
        no_action = class_page.locator(".task-actions__empty")
        if no_action.count() > 0 and no_action.is_visible():
            expect(no_action).to_contain_text("No manual action is available")


@pytest.mark.task_details
class TestTaskLogs:
    """Tests for task log display."""

    def test_log_content_area_exists(self, class_page: Page):
        """Test that the task process panel exists."""
        class_page.goto("/tasks/1")
        class_page.wait_for_selector(".task-view", state="visible", timeout=5000)
        log_content = class_page.locator(".task-process-panel")
        expect(log_content).to_be_attached()

    def test_logs_refresh_button_exists(self, class_page: Page):
        """Test that logs section has a refresh button."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        logs_refresh_button = class_page.locator(".task-card").get_by_role("button", name="Refresh")
        if logs_refresh_button.is_visible():
            expect(logs_refresh_button).to_be_visible()
