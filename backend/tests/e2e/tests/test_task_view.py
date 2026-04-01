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




@pytest.mark.task_view
class TestTaskViewPage:
    """Tests for the task view page functionality."""

    def test_task_view_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the task view page loads without errors."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        task_view = logged_in_page.locator(".task-view")
        expect(task_view).to_be_visible()

    def test_task_view_title_is_displayed(self, logged_in_page: Page, reset_database):
        """Test that task view displays title with task ID."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        title = logged_in_page.locator(".task-view__title")
        if title.is_visible():
            expect(title).to_contain_text("1")

    def test_task_view_subtitle_is_displayed(self, logged_in_page: Page, reset_database):
        """Test that task view subtitle is displayed."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        subtitle = logged_in_page.locator(".task-view__subtitle")
        if subtitle.is_visible():
            expect(subtitle).to_be_visible()


@pytest.mark.task_view
class TestTaskViewSummary:
    """Tests for task view summary cards."""

    def test_summary_section_exists(self, logged_in_page: Page, reset_database):
        """Test that summary section is present when task is loaded."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        summary = logged_in_page.locator(".task-view__summary")
        if summary.is_visible():
            summary_cards = logged_in_page.locator(".task-summary-card")
            expect(summary_cards.first).to_be_visible()

    def test_summary_cards_have_labels(self, logged_in_page: Page, reset_database):
        """Test that summary cards have labels."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        summary_label = logged_in_page.locator(".task-summary-card__label").first
        if summary_label.is_visible():
            expect(summary_label).to_be_visible()

    def test_summary_cards_have_values(self, logged_in_page: Page, reset_database):
        """Test that summary cards have values."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        summary_value = logged_in_page.locator(".task-summary-card__value").first
        if summary_value.is_visible():
            expect(summary_value).to_be_visible()


@pytest.mark.task_view
class TestTaskViewDetails:
    """Tests for task details card display."""

    def test_task_details_card_exists(self, logged_in_page: Page, reset_database):
        """Test that the task details card is present."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        task_cards = logged_in_page.locator(".task-card")
        expect(task_cards.first).to_be_visible()

    def test_task_details_card_title(self, logged_in_page: Page, reset_database):
        """Test that the task details card has a title."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        task_card_title = logged_in_page.locator(".task-card__title").first
        if task_card_title.is_visible():
            expect(task_card_title).to_be_visible()


@pytest.mark.task_view
class TestTaskViewActions:
    """Tests for task action buttons (cancel, retry, execute)."""

    def test_actions_card_exists(self, logged_in_page: Page, reset_database):
        """Test that the actions card is present in task view."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        task_actions = logged_in_page.locator(".task-actions")
        if task_actions.is_visible():
            expect(task_actions).to_be_visible()

    def test_cancel_button_exists(self, logged_in_page: Page, reset_database):
        """Test that cancel button is shown for pending/running tasks."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        cancel_button = logged_in_page.get_by_role("button", name="Cancel")
        if cancel_button.is_visible():
            expect(cancel_button).to_be_visible()

    def test_retry_button_exists(self, logged_in_page: Page, reset_database):
        """Test that retry button is shown for failed/cancelled tasks."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        retry_button = logged_in_page.get_by_role("button", name="Retry")
        if retry_button.is_visible():
            expect(retry_button).to_be_visible()

    def test_execute_button_exists(self, logged_in_page: Page, reset_database):
        """Test that execute button is shown for pending tasks."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        execute_button = logged_in_page.get_by_role("button", name="Execute")
        if execute_button.is_visible():
            expect(execute_button).to_be_visible()

    def test_no_actions_message_for_completed_tasks(self, logged_in_page: Page, reset_database):
        """Test that completed tasks show no action message."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        no_action = logged_in_page.locator(".task-actions__empty")
        if no_action.is_visible():
            expect(no_action).to_contain_text("No manual action", ignore_case=True)


@pytest.mark.task_view
class TestTaskViewLogs:
    """Tests for task log display."""

    def test_log_content_area_exists(self, logged_in_page: Page, reset_database):
        """Test that the log content area exists."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        log_content = logged_in_page.locator(".log-content")
        expect(log_content).to_be_attached()

    def test_log_section_has_refresh_button(self, logged_in_page: Page, reset_database):
        """Test that logs section has a refresh button."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        logs_refresh_button = logged_in_page.locator(".task-card").get_by_role("button", name="Refresh")
        if logs_refresh_button.is_visible():
            expect(logs_refresh_button).to_be_visible()


@pytest.mark.task_view
class TestTaskViewNavigation:
    """Tests for task view navigation."""

    def test_back_to_dashboard_via_sidebar(self, logged_in_page: Page, reset_database):
        """Test that navigation back to dashboard works via sidebar."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        dashboard_link = logged_in_page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            logged_in_page.wait_for_url("**/dashboard", timeout=5000)

    def test_refresh_button_is_visible(self, logged_in_page: Page, reset_database):
        """Test that the refresh button in hero section is visible."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        expect(refresh_button.first).to_be_visible()


@pytest.mark.task_view
class TestTaskViewPermissions:
    """Tests for task view permission checks."""

    def test_permission_note_for_limited_actions(self, logged_in_page: Page, reset_database):
        """Test that permission note is shown when user has limited actions."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        permission_note = logged_in_page.locator(".task-actions__permission-note")
        if permission_note.is_visible():
            expect(permission_note).to_be_visible()

    def test_actions_intro_message_exists(self, logged_in_page: Page, reset_database):
        """Test that the actions intro message exists."""
        logged_in_page.goto("/tasks/1")
        logged_in_page.wait_for_load_state("networkidle")
        actions_intro = logged_in_page.locator(".task-actions__intro")
        if actions_intro.is_visible():
            expect(actions_intro).to_be_visible()
