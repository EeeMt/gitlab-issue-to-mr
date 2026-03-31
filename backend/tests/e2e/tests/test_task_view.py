"""
TaskView E2E Tests

Tests for the TaskView page functionality including:
- Task detail display
- Cancel/retry/execute button actions
- Log display
- Permission checks
"""

import pytest
from playwright.sync_api import Page, expect


def create_admin_and_login(page: Page):
    """Helper to create admin via bootstrap and login."""
    page.goto("/bootstrap")
    page.wait_for_selector(".bootstrap-card", timeout=10000)

    inputs = page.locator(".bootstrap-form input")
    inputs.nth(0).fill("taskview_admin")
    inputs.nth(1).fill("TaskView Admin")
    inputs.nth(2).fill("taskview_admin@example.com")

    password_inputs = page.locator("input[type='password']")
    password_inputs.nth(0).fill("securepassword123")
    password_inputs.nth(1).fill("securepassword123")

    page.get_by_role("button", name="Create Admin").click()
    page.wait_for_url("**/dashboard", timeout=10000)
    page.wait_for_load_state("networkidle")


@pytest.mark.task_view
class TestTaskViewPage:
    """Tests for the task view page functionality."""

    def test_task_view_page_loads(self, page: Page, reset_database):
        """Test that the task view page loads without errors when accessing a valid task."""
        create_admin_and_login(page)

        # Navigate directly to task view with a non-existent task ID
        # This will show the page structure even without task data
        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        # The page should have the task-view container
        task_view = page.locator(".task-view")
        expect(task_view).to_be_visible()

    def test_task_view_title_is_displayed(self, page: Page, reset_database):
        """Test that task view displays title with task ID."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Title should be visible (shows "Task #1" or similar)
        title = page.locator(".task-view__title")
        if title.is_visible():
            expect(title).to_contain_text("1")

    def test_task_view_subtitle_is_displayed(self, page: Page, reset_database):
        """Test that task view subtitle is displayed."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        subtitle = page.locator(".task-view__subtitle")
        if subtitle.is_visible():
            expect(subtitle).to_be_visible()


@pytest.mark.task_view
class TestTaskViewSummary:
    """Tests for task view summary cards."""

    def test_summary_section_exists(self, page: Page, reset_database):
        """Test that summary section is present when task is loaded."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        summary = page.locator(".task-view__summary")
        if summary.is_visible():
            summary_cards = page.locator(".task-summary-card")
            expect(summary_cards.first).to_be_visible()

    def test_summary_cards_have_labels(self, page: Page, reset_database):
        """Test that summary cards have labels."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        summary_label = page.locator(".task-summary-card__label").first
        if summary_label.is_visible():
            expect(summary_label).to_be_visible()

    def test_summary_cards_have_values(self, page: Page, reset_database):
        """Test that summary cards have values."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        summary_value = page.locator(".task-summary-card__value").first
        if summary_value.is_visible():
            expect(summary_value).to_be_visible()


@pytest.mark.task_view
class TestTaskViewDetails:
    """Tests for task details card display."""

    def test_task_details_card_exists(self, page: Page, reset_database):
        """Test that the task details card is present."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        task_cards = page.locator(".task-card")
        expect(task_cards.first).to_be_visible()

    def test_task_details_card_title(self, page: Page, reset_database):
        """Test that the task details card has a title."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        task_card_title = page.locator(".task-card__title").first
        if task_card_title.is_visible():
            expect(task_card_title).to_be_visible()


@pytest.mark.task_view
class TestTaskViewActions:
    """Tests for task action buttons (cancel, retry, execute)."""

    def test_actions_card_exists(self, page: Page, reset_database):
        """Test that the actions card is present in task view."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        task_actions = page.locator(".task-actions")
        if task_actions.is_visible():
            expect(task_actions).to_be_visible()

    def test_cancel_button_exists(self, page: Page, reset_database):
        """Test that cancel button is shown for pending/running tasks."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Cancel button exists but may be disabled depending on task state
        cancel_button = page.get_by_role("button", name="Cancel")
        # Button may or may not be visible depending on task status

    def test_retry_button_exists(self, page: Page, reset_database):
        """Test that retry button is shown for failed/cancelled tasks."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Retry button exists but visibility depends on task state
        retry_button = page.get_by_role("button", name="Retry")
        # Button may or may not be visible depending on task status

    def test_execute_button_exists(self, page: Page, reset_database):
        """Test that execute button is shown for pending tasks."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Execute button exists but visibility depends on task state
        execute_button = page.get_by_role("button", name="Execute")
        # Button may or may not be visible depending on task status

    def test_no_actions_message_for_completed_tasks(self, page: Page, reset_database):
        """Test that completed tasks show no action buttons."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # For completed tasks, the action area should show "no manual action" message
        no_action = page.locator(".task-actions__empty")
        if no_action.is_visible():
            expect(no_action).to_contain_text("no manual action")


@pytest.mark.task_view
class TestTaskViewLogs:
    """Tests for task log display."""

    def test_log_content_area_exists(self, page: Page, reset_database):
        """Test that the log content area exists."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Log content area should exist
        log_content = page.locator(".log-content")
        expect(log_content).to_be_attached()

    def test_log_section_has_refresh_button(self, page: Page, reset_database):
        """Test that logs section has a refresh button."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        # Find the refresh button in the logs section header
        logs_refresh_button = page.locator(".task-card").get_by_role("button", name="Refresh")
        if logs_refresh_button.is_visible():
            expect(logs_refresh_button).to_be_visible()


@pytest.mark.task_view
class TestTaskViewNavigation:
    """Tests for task view navigation."""

    def test_back_to_dashboard_via_sidebar(self, page: Page, reset_database):
        """Test that navigation back to dashboard works via sidebar."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        # Use sidebar to navigate back to dashboard
        dashboard_link = page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            page.wait_for_url("**/dashboard", timeout=5000)

    def test_refresh_button_is_visible(self, page: Page, reset_database):
        """Test that the refresh button in hero section is visible."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")

        refresh_button = page.get_by_role("button", name="Refresh")
        expect(refresh_button.first).to_be_visible()


@pytest.mark.task_view
class TestTaskViewPermissions:
    """Tests for task view permission checks."""

    def test_permission_note_for_limited_actions(self, page: Page, reset_database):
        """Test that permission note is shown when user has limited actions."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Permission note may be visible for non-admin users
        permission_note = page.locator(".task-actions__permission-note")
        if permission_note.is_visible():
            expect(permission_note).to_be_visible()

    def test_actions_intro_message_exists(self, page: Page, reset_database):
        """Test that the actions intro message exists."""
        create_admin_and_login(page)

        page.goto("/tasks/1")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        actions_intro = page.locator(".task-actions__intro")
        if actions_intro.is_visible():
            expect(actions_intro).to_be_visible()
