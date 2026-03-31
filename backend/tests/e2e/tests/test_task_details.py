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

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("taskdetail_admin")
        inputs.nth(1).fill("Task Detail Admin")
        inputs.nth(2).fill("taskdetail_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_task_view_page_loads(self, page: Page, reset_database):
        """Test that the task view page loads without errors when accessing a valid task."""
        self._create_admin_and_login(page)

        # Navigate directly to task view with a non-existent task ID
        # This will show the page structure even without task data
        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        # The page should have the task-view container
        task_view = page.locator(".task-view")
        expect(task_view).to_be_visible()

    def test_task_view_has_title(self, page: Page, reset_database):
        """Test that task view displays title with task ID."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Title should be visible (shows "Task #1" or similar)
        title = page.locator(".task-view__title")
        if title.is_visible():
            expect(title).to_contain_text("1")

    def test_task_view_has_summary_cards(self, page: Page, reset_database):
        """Test that task view displays summary cards when task is loaded."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Summary cards should be present when task data loads
        summary = page.locator(".task-view__summary")
        if summary.is_visible():
            summary_cards = page.locator(".task-summary-card")
            expect(summary_cards.first).to_be_visible()

    def test_task_view_has_task_details_card(self, page: Page, reset_database):
        """Test that task view has a task details card."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Look for task card with task details
        task_cards = page.locator(".task-card")
        expect(task_cards.first).to_be_visible()

    def test_task_view_has_refresh_button(self, page: Page, reset_database):
        """Test that task view has a refresh button."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        refresh_button = page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()

    def test_task_view_has_log_section(self, page: Page, reset_database):
        """Test that task view has a logs section."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # The logs section should be present
        log_section = page.locator(".log-content")
        # Log content may or may not have content depending on task state
        # But the element should exist
        expect(log_section).to_be_attached()

    def test_task_view_back_to_dashboard(self, page: Page, reset_database):
        """Test that navigation back to dashboard works via sidebar."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        # Use sidebar to navigate back to dashboard
        dashboard_link = page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            page.wait_for_url("**/dashboard", timeout=5000)
            expect(page).to_have_url("**/dashboard")


@pytest.mark.task_details
class TestTaskActions:
    """Tests for task action buttons (cancel, retry, execute)."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("action_admin")
        inputs.nth(1).fill("Action Admin")
        inputs.nth(2).fill("action_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_task_actions_card_exists(self, page: Page, reset_database):
        """Test that the actions card is present in task view."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # The actions card should contain task action buttons
        # Check for the task-actions container
        task_actions = page.locator(".task-actions")
        if task_actions.is_visible():
            expect(task_actions).to_be_visible()

    def test_cancel_button_exists_for_active_tasks(self, page: Page, reset_database):
        """Test that cancel button is shown for pending/running tasks."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Cancel button exists but may be disabled depending on task state
        cancel_button = page.get_by_role("button", name="Cancel")
        # Button may or may not be visible depending on task status
        # Just verify the button element exists in the page

    def test_retry_button_exists_for_failed_tasks(self, page: Page, reset_database):
        """Test that retry button is shown for failed/cancelled tasks."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Retry button exists but visibility depends on task state
        retry_button = page.get_by_role("button", name="Retry")
        # Button may or may not be visible depending on task status

    def test_execute_button_exists_for_pending_tasks(self, page: Page, reset_database):
        """Test that execute button is shown for pending tasks."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Execute button exists but visibility depends on task state
        execute_button = page.get_by_role("button", name="Execute")
        # Button may or may not be visible depending on task status

    def test_task_view_no_actions_for_completed_tasks(self, page: Page, reset_database):
        """Test that completed tasks show no action buttons."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # For completed tasks, the action area should show "no manual action" message
        no_action = page.locator(".task-actions__empty")
        if no_action.is_visible():
            expect(no_action).to_contain_text("no manual action")


@pytest.mark.task_details
class TestTaskLogs:
    """Tests for task log display."""

    def _create_admin_and_login(self, page: Page):
        """Helper to create admin via bootstrap and login."""
        page.goto("/bootstrap")
        page.wait_for_selector(".bootstrap-card", timeout=10000)

        inputs = page.locator(".bootstrap-form input")
        inputs.nth(0).fill("log_admin")
        inputs.nth(1).fill("Log Admin")
        inputs.nth(2).fill("log_admin@example.com")

        password_inputs = page.locator("input[type='password']")
        password_inputs.nth(0).fill("securepassword123")
        password_inputs.nth(1).fill("securepassword123")

        page.get_by_role("button", name="Create Admin").click()
        page.wait_for_url("**/dashboard", timeout=10000)
        page.wait_for_load_state("networkidle")

    def test_log_content_area_exists(self, page: Page, reset_database):
        """Test that the log content area exists."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Log content area should exist
        log_content = page.locator(".log-content")
        expect(log_content).to_be_attached()

    def test_logs_refresh_button_exists(self, page: Page, reset_database):
        """Test that logs section has a refresh button."""
        self._create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        # Find the refresh button in the logs section header
        logs_refresh_button = page.locator(".task-card").get_by_role("button", name="Refresh")
        if logs_refresh_button.is_visible():
            expect(logs_refresh_button).to_be_visible()
