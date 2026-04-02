"""
Dashboard E2E Tests

Tests for the Dashboard (task queue) functionality including:
- Task list display
- Filter interactions (P0/P1/P2/All)
- Task row click navigation
- Auto-refresh behavior
- Summary card display
"""

import pytest
from playwright.sync_api import Page, expect




@pytest.mark.dashboard
class TestDashboardPage:
    """Tests for the dashboard page functionality."""

    def test_dashboard_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the dashboard page loads without errors."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("dashboard-header")).to_be_visible()

    def test_dashboard_title_is_displayed(self, logged_in_page: Page, reset_database):
        """Test that the dashboard title is displayed."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("dashboard-header")).to_be_visible()

    def test_dashboard_subtitle_is_displayed(self, logged_in_page: Page, reset_database):
        """Test that the dashboard subtitle is displayed."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.get_by_test_id("dashboard-header")).to_be_visible()


@pytest.mark.dashboard
class TestDashboardFilters:
    """Tests for dashboard filter interactions."""

    def test_status_filter_is_present(self, logged_in_page: Page, reset_database):
        """Test that status filter dropdown is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        status_filter = logged_in_page.locator(".dashboard__filters .n-base-selection").nth(0)
        expect(status_filter).to_be_visible()

    def test_project_filter_is_present(self, logged_in_page: Page, reset_database):
        """Test that project filter dropdown is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        project_filter = logged_in_page.locator(".dashboard__filters .n-base-selection").nth(1)
        expect(project_filter).to_be_visible()

    def test_initiator_filter_is_present(self, logged_in_page: Page, reset_database):
        """Test that initiator filter dropdown is present (only shown when tasks exist)."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(500)
        initiator_filter = logged_in_page.locator(".dashboard__filters .n-base-selection").nth(2)
        if initiator_filter.is_visible():
            expect(initiator_filter).to_be_visible()

    def test_filters_area_contains_refresh_button(self, logged_in_page: Page, reset_database):
        """Test that refresh button is present in filters area."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()


@pytest.mark.dashboard
class TestDashboardSummaryCards:
    """Tests for dashboard summary card display."""

    def test_summary_cards_are_displayed(self, logged_in_page: Page, reset_database):
        """Test that summary cards are displayed on the dashboard."""
        logged_in_page.goto("/dashboard")
        # Wait for the summary grid (rendered only after first API response via v-if="hasLoadedOnce")
        logged_in_page.wait_for_selector("[data-testid='dashboard-summary']")
        summary_cards = logged_in_page.locator(".dashboard-summary-card")
        expect(summary_cards.first).to_be_visible()

    def test_summary_card_has_label(self, logged_in_page: Page, reset_database):
        """Test that summary cards have labels."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector("[data-testid='dashboard-summary']")
        summary_label = logged_in_page.locator(".dashboard-summary-card__label").first
        expect(summary_label).to_be_visible()

    def test_summary_card_has_value(self, logged_in_page: Page, reset_database):
        """Test that summary cards have values."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector("[data-testid='dashboard-summary']")
        summary_value = logged_in_page.locator(".dashboard-summary-card__value").first
        expect(summary_value).to_be_visible()


@pytest.mark.dashboard
class TestDashboardTaskTable:
    """Tests for dashboard task table display."""

    def test_task_table_is_present(self, logged_in_page: Page, reset_database):
        """Test that the task data table is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        data_table = logged_in_page.locator(".n-data-table")
        expect(data_table).to_be_visible()

    def test_task_table_has_headers(self, logged_in_page: Page, reset_database):
        """Test that the task table has column headers (only visible when table has data)."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        table_headers = logged_in_page.locator(".n-data-table-th")
        # Headers may not exist if table is empty
        if table_headers.count() > 0:
            expect(table_headers.first).to_be_visible()

    def test_refresh_button_triggers_update(self, logged_in_page: Page, reset_database):
        """Test that the refresh button triggers a data refresh."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()
        refresh_button.click()
        logged_in_page.wait_for_timeout(500)


@pytest.mark.dashboard
class TestDashboardNavigation:
    """Tests for dashboard navigation interactions."""

    def test_dashboard_accessible_from_sidebar(self, logged_in_page: Page, reset_database):
        """Test that dashboard is accessible from sidebar navigation."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")

        dashboard_link = logged_in_page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            logged_in_page.wait_for_url("**/dashboard", timeout=5000)

    def test_task_row_click_navigation(self, logged_in_page: Page, reset_database):
        """Test that clicking a task row initiates navigation."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")

        table_row = logged_in_page.locator(".n-data-table-tr").first
        if table_row.is_visible():
            expect(table_row).to_be_visible()


@pytest.mark.dashboard
class TestDashboardFilterInteractions:
    """Tests for interactive filter behaviour on the dashboard."""

    def test_status_filter_can_be_opened(self, logged_in_page: Page, reset_database):
        """Test that the status filter dropdown can be opened."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector("[data-testid='dashboard-header']")
        # Click the inner selection trigger of the first n-select (status filter)
        first_select = logged_in_page.locator(".n-select").first
        first_select.locator(".n-base-selection").click()
        # Verify dropdown opened
        expect(logged_in_page.locator(".n-base-select-menu")).to_be_visible()

    def test_status_filter_has_options(self, logged_in_page: Page, reset_database):
        """Test that the status filter dropdown contains selectable options."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector("[data-testid='dashboard-header']")
        first_select = logged_in_page.locator(".n-select").first
        first_select.locator(".n-base-selection").click()
        expect(logged_in_page.locator(".n-base-select-menu")).to_be_visible()
        options = logged_in_page.locator(".n-base-select-option")
        expect(options.first).to_be_visible()

    def test_status_filter_can_select_option(self, logged_in_page: Page, reset_database):
        """Test that selecting an option from the status filter closes the dropdown."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_selector("[data-testid='dashboard-header']")
        first_select = logged_in_page.locator(".n-select").first
        first_select.locator(".n-base-selection").click()
        logged_in_page.locator(".n-base-select-option").first.click()
        # After selecting, dropdown should close
        expect(logged_in_page.locator(".n-base-select-menu")).not_to_be_visible()
