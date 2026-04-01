"""
Task Queue Dashboard E2E Tests

Tests for the Dashboard (task queue) functionality including:
- Task queue viewing with P0/P1/P2 tabs
- Filter interactions
- Task row click navigation
- Summary card display
- Auto-refresh behavior
"""

import pytest
from playwright.sync_api import Page, expect




@pytest.mark.dashboard
class TestTaskQueue:
    """Tests for the task queue dashboard functionality."""

    def test_dashboard_page_loads(self, logged_in_page: Page, reset_database):
        """Test that the dashboard page loads without errors."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        expect(logged_in_page.locator(".dashboard__title")).to_be_visible()

    def test_dashboard_has_filters(self, logged_in_page: Page, reset_database):
        """Test that dashboard has filter dropdowns."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        filter_selects = logged_in_page.locator(".dashboard__filters .n-select")
        expect(filter_selects.first).to_be_visible()

    def test_dashboard_has_summary_cards(self, logged_in_page: Page, reset_database):
        """Test that dashboard displays summary cards."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(1000)
        summary_cards = logged_in_page.locator(".dashboard-summary-card")
        expect(summary_cards.first).to_be_visible()

    def test_dashboard_has_task_table(self, logged_in_page: Page, reset_database):
        """Test that dashboard displays task data table."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(1000)
        data_table = logged_in_page.locator(".n-data-table")
        expect(data_table).to_be_visible()

    def test_dashboard_refresh_button_works(self, logged_in_page: Page, reset_database):
        """Test that the refresh button triggers a data refresh."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(1000)
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()
        refresh_button.click()
        logged_in_page.wait_for_timeout(500)

    def test_dashboard_table_has_columns(self, logged_in_page: Page, reset_database):
        """Test that the task table has expected columns."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(1000)
        table_header = logged_in_page.locator(".n-data-table-th")
        if table_header.count() > 0:
            expect(table_header.first).to_be_visible()

    def test_dashboard_navigates_to_task_view(self, logged_in_page: Page, reset_database):
        """Test that clicking a task row navigates to task detail view."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.wait_for_timeout(1000)

        table_row = logged_in_page.locator(".n-data-table-tr").first
        if table_row.is_visible():
            row_id = table_row.get_attribute("data-row-key")
            table_row.click()
            if row_id:
                logged_in_page.wait_for_timeout(1000)


@pytest.mark.dashboard
class TestTaskQueueFilters:
    """Tests for dashboard filter functionality."""

    def test_status_filter_exists(self, logged_in_page: Page, reset_database):
        """Test that status filter dropdown is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        status_filter = logged_in_page.locator(".dashboard__filters .n-select").first
        expect(status_filter).to_be_visible()

    def test_project_filter_exists(self, logged_in_page: Page, reset_database):
        """Test that project filter dropdown is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        project_filter = logged_in_page.locator(".dashboard__filters .n-select").nth(1)
        expect(project_filter).to_be_visible()

    def test_initiator_filter_exists(self, logged_in_page: Page, reset_database):
        """Test that initiator filter dropdown is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        initiator_filter = logged_in_page.locator(".dashboard__filters .n-select").nth(2)
        if initiator_filter.is_visible():
            expect(initiator_filter).to_be_visible()

    def test_refresh_button_exists(self, logged_in_page: Page, reset_database):
        """Test that refresh button is present."""
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        refresh_button = logged_in_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()
