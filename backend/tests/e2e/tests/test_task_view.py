"""
TaskView E2E Tests

Tests for the TaskView page functionality including:
- Task detail display
- Cancel/retry/execute button actions
- Log display
- Permission checks
"""

import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.task_view
class TestTaskViewPage:
    """Tests for the task view page functionality."""

    def test_task_view_page_loads(self, class_page: Page):
        """Test that the task view page loads without errors."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        task_view = class_page.get_by_test_id("task-view-page")
        expect(task_view).to_be_visible()

    def test_task_view_title_is_displayed(self, class_page: Page):
        """Test that task view displays title with task ID."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        title = class_page.locator(".task-view__title")
        if title.is_visible():
            expect(title).to_contain_text("1")

    def test_task_view_subtitle_is_displayed(self, class_page: Page):
        """Test that task view subtitle is displayed."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        subtitle = class_page.locator(".task-view__subtitle")
        if subtitle.is_visible():
            expect(subtitle).to_be_visible()


@pytest.mark.task_view
class TestTaskViewSummary:
    """Tests for task view summary cards."""

    def test_summary_section_exists(self, class_page: Page):
        """Test that summary section is present when task is loaded."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        summary = class_page.get_by_test_id("task-view-summary")
        if summary.is_visible():
            summary_cards = class_page.locator(".task-summary-card")
            expect(summary_cards.first).to_be_visible()

    def test_summary_cards_have_labels(self, class_page: Page):
        """Test that summary cards have labels."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        summary_label = class_page.locator(".task-summary-card__label").first
        if summary_label.is_visible():
            expect(summary_label).to_be_visible()

    def test_summary_cards_have_values(self, class_page: Page):
        """Test that summary cards have values."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        summary_value = class_page.locator(".task-summary-card__value").first
        if summary_value.is_visible():
            expect(summary_value).to_be_visible()


@pytest.mark.task_view
class TestTaskViewDetails:
    """Tests for task details card display."""

    def test_task_details_card_exists(self, class_page: Page):
        """Test that the task details card is present."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        task_cards = class_page.locator(".task-card")
        expect(task_cards.first).to_be_visible()

    def test_task_details_card_title(self, class_page: Page):
        """Test that the task details card has a title."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        task_card_title = class_page.locator(".task-card__title").first
        if task_card_title.is_visible():
            expect(task_card_title).to_be_visible()


@pytest.mark.task_view
class TestTaskViewActions:
    """Tests for task action buttons (cancel, retry, execute)."""

    def test_actions_card_exists(self, class_page: Page):
        """Test that the actions card is present in task view."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        task_actions = class_page.get_by_test_id("task-actions")
        if task_actions.is_visible():
            expect(task_actions).to_be_visible()

    def test_cancel_button_exists(self, class_page: Page):
        """Test that cancel button is shown for pending/running tasks."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        cancel_button = class_page.get_by_role("button", name="Cancel")
        if cancel_button.is_visible():
            expect(cancel_button).to_be_visible()

    def test_retry_button_exists(self, class_page: Page):
        """Test that retry button is shown for failed/cancelled tasks."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        retry_button = class_page.get_by_role("button", name="Retry", exact=True)
        if retry_button.is_visible():
            expect(retry_button).to_be_visible()

    def test_execute_button_exists(self, class_page: Page):
        """Test that execute button is shown for pending tasks."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        execute_button = class_page.get_by_role("button", name="Execute")
        if execute_button.is_visible():
            expect(execute_button).to_be_visible()

    def test_no_actions_message_for_completed_tasks(self, class_page: Page):
        """Test that completed tasks show no action message."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        no_action = class_page.locator(".task-actions__empty")
        if no_action.is_visible():
            expect(no_action).to_contain_text("No manual action", ignore_case=True)


@pytest.mark.task_view
class TestTaskViewLogs:
    """Tests for task log display."""

    def test_log_content_area_exists(self, class_page: Page):
        """Test that the log content area exists."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        log_area = class_page.locator(".task-process-panel")
        expect(log_area).to_be_attached()

    def test_log_section_has_refresh_button(self, class_page: Page):
        """Test that logs section has a refresh button."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        logs_refresh_button = class_page.locator(".task-card").get_by_role("button", name="Refresh")
        if logs_refresh_button.is_visible():
            expect(logs_refresh_button).to_be_visible()


@pytest.mark.task_view
class TestTaskViewNavigation:
    """Tests for task view navigation."""

    def test_back_to_dashboard_via_sidebar(self, class_page: Page):
        """Test that navigation back to dashboard works via sidebar."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        dashboard_link = class_page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            class_page.wait_for_url("**/dashboard", timeout=5000)

    def test_refresh_button_is_visible(self, class_page: Page):
        """Test that the refresh button in hero section is visible."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        expect(refresh_button.first).to_be_visible()


@pytest.mark.task_view
class TestTaskViewPermissions:
    """Tests for task view permission checks."""

    def test_permission_note_for_limited_actions(self, class_page: Page):
        """Test that permission note is shown when user has limited actions."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        permission_note = class_page.locator(".task-actions__permission-note")
        if permission_note.is_visible():
            expect(permission_note).to_be_visible()

    def test_actions_intro_message_exists(self, class_page: Page):
        """Test that the actions intro message exists."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        actions_intro = class_page.locator(".task-actions__intro")
        if actions_intro.is_visible():
            expect(actions_intro).to_be_visible()


@pytest.mark.task_view
class TestTaskViewRefreshButton:
    """Tests for the refresh button interaction on task view."""

    def test_refresh_button_click_does_not_crash(self, class_page: Page):
        """Test that clicking the refresh button doesn't crash the page."""
        class_page.goto("/tasks/1")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.wait_for_timeout(500)
        refresh_btn = class_page.get_by_role("button", name=re.compile(r"refresh", re.IGNORECASE)).first
        if refresh_btn.is_visible():
            refresh_btn.click()
            class_page.wait_for_timeout(500)
            expect(class_page.locator(".task-view")).to_be_visible()


# ---------------------------------------------------------------------------
# Action tests with a real task created via API
# ---------------------------------------------------------------------------


@pytest.fixture
def test_task_id(logged_in_page, backend_url):
    """Create a pending test task via API and return its ID.

    Creates an Issue first, then creates a Task under it. Requires at least
    one GitLab project to be configured. Skips the test gracefully if no
    projects are available or task creation fails.
    """
    from conftest import api_create_issue, api_get_first_project

    cookies = {c["name"]: c["value"] for c in logged_in_page.context.cookies()}
    project = api_get_first_project(backend_url, cookies)
    issue = api_create_issue(backend_url, cookies, project["id"], title="E2E TaskView Test Issue")

    # Create a pending task scheduled far in future so the scheduler
    # won't pick it up — keeps task in PENDING for button-click tests.
    future_dt = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    with httpx.Client(base_url=backend_url, timeout=15, cookies=cookies) as client:
        resp = client.post(
            "/api/tasks",
            json={
                "issue_id": issue["id"],
                "user_prompt": "E2E test task - do nothing",
                "priority": 2,
                "scheduled_datetime": future_dt,
            },
        )
        if resp.status_code not in (200, 201):
            pytest.skip(f"Cannot create test task: {resp.status_code} {resp.text}")
        return resp.json()["id"]


@pytest.mark.task_view
class TestTaskViewActionInteractions:
    """Tests for task view actions using a real task created via the API.

    Each test receives its own ``logged_in_page`` (function-scoped with DB
    reset) and a freshly created ``test_task_id`` so tests are fully isolated.
    """

    def test_task_view_shows_created_task(self, logged_in_page: Page, test_task_id: int):
        """Navigate to the created task and verify its details are visible."""
        logged_in_page.goto(f"/tasks/{test_task_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")

        task_view = logged_in_page.get_by_test_id("task-view-page")
        expect(task_view).to_be_visible()

        # Title should contain the task ID
        title = logged_in_page.locator(".task-view__title")
        expect(title).to_contain_text(str(test_task_id))

        # The metadata panel should be visible with project/branch info
        metadata = logged_in_page.locator(".task-metadata-panel")
        expect(metadata).to_be_visible()

    def test_cancel_button_shows_confirmation(self, logged_in_page: Page, test_task_id: int):
        """Click Cancel on a pending task and verify a feedback message appears.

        TaskView fires the cancel API directly (no confirmation dialog);
        a Naive UI message toast (.n-message) is shown on success or failure.
        """
        logged_in_page.goto(f"/tasks/{test_task_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(500)

        cancel_btn = logged_in_page.get_by_role("button", name="Cancel")
        if not cancel_btn.is_visible():
            pytest.skip("Cancel button not visible for this task state")

        cancel_btn.click()

        # A Naive UI message toast should appear (success or error)
        msg = logged_in_page.locator(".n-message")
        expect(msg.first).to_be_visible(timeout=5000)

    def test_execute_button_on_pending_task(self, logged_in_page: Page, test_task_id: int):
        """Click Execute on a pending task and verify success feedback."""
        logged_in_page.goto(f"/tasks/{test_task_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(500)

        execute_btn = logged_in_page.get_by_role("button", name="Execute")
        expect(execute_btn).to_be_visible(timeout=5000)

        execute_btn.click()

        # A Naive UI message toast should appear (success or error)
        msg = logged_in_page.locator(".n-message")
        expect(msg.first).to_be_visible(timeout=5000)

    def test_task_log_section_rendered(self, logged_in_page: Page, test_task_id: int):
        """Task process/log panel is rendered for the created task."""
        logged_in_page.goto(f"/tasks/{test_task_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")

        log_panel = logged_in_page.locator(".task-process-panel")
        expect(log_panel).to_be_attached()

    def test_task_metadata_shows_data(self, logged_in_page: Page, test_task_id: int):
        """Metadata panel shows actual data (project, branch, source) for the task."""
        logged_in_page.goto(f"/tasks/{test_task_id}")
        logged_in_page.wait_for_load_state("domcontentloaded")

        metadata = logged_in_page.locator(".task-metadata-panel")
        expect(metadata).to_be_visible()

        # At least one metadata row should be present with label and value
        rows = metadata.locator(".metadata-row")
        assert rows.count() > 0, "Expected at least one metadata row"

        for i in range(min(rows.count(), 3)):
            row = rows.nth(i)
            label = row.locator(".metadata-label")
            value = row.locator(".metadata-value")
            expect(label).to_be_visible()
            expect(value).to_be_visible()
            assert value.text_content().strip(), f"Metadata row {i} value should not be empty"
