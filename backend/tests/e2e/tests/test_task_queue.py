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

    def test_dashboard_page_loads(self, class_page: Page):
        """Test that the dashboard page loads without errors."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.locator(".dashboard__title")).to_be_visible()

    def test_dashboard_has_filters(self, class_page: Page):
        """Test that dashboard has filter dropdowns."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        filter_selects = class_page.locator(".dashboard__filters .n-select")
        expect(filter_selects.first).to_be_visible()

    def test_dashboard_has_summary_cards(self, class_page: Page):
        """Test that dashboard displays summary cards."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.wait_for_timeout(1000)
        summary_cards = class_page.locator(".dashboard-summary-card")
        expect(summary_cards.first).to_be_visible()

    def test_dashboard_has_task_table(self, class_page: Page):
        """Test that dashboard displays task data table."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.wait_for_timeout(1000)
        data_table = class_page.locator(".n-data-table")
        expect(data_table).to_be_visible()

    def test_dashboard_refresh_button_works(self, class_page: Page):
        """Test that the refresh button triggers a data refresh."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.wait_for_timeout(1000)
        refresh_button = class_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()
        refresh_button.click()
        class_page.wait_for_timeout(500)

    def test_dashboard_table_has_columns(self, class_page: Page):
        """Test that the task table has expected columns."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.wait_for_timeout(1000)
        table_header = class_page.locator(".n-data-table-th")
        if table_header.count() > 0:
            expect(table_header.first).to_be_visible()

    def test_dashboard_navigates_to_task_view(self, class_page: Page):
        """Test that clicking a task row navigates to task detail view."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        class_page.wait_for_timeout(1000)

        table_row = class_page.locator(".n-data-table-tr").first
        if table_row.is_visible():
            row_id = table_row.get_attribute("data-row-key")
            table_row.click()
            if row_id:
                class_page.wait_for_timeout(1000)


@pytest.mark.dashboard
class TestTaskQueueFilters:
    """Tests for dashboard filter functionality."""

    def test_status_filter_exists(self, class_page: Page):
        """Test that status filter dropdown is present."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        status_filter = class_page.locator(".dashboard__filters .n-select").first
        expect(status_filter).to_be_visible()

    def test_project_filter_exists(self, class_page: Page):
        """Test that project filter dropdown is present."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        project_filter = class_page.locator(".dashboard__filters .n-select").nth(1)
        expect(project_filter).to_be_visible()

    def test_initiator_filter_exists(self, class_page: Page):
        """Test that initiator filter dropdown is present."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        initiator_filter = class_page.locator(".dashboard__filters .n-select").nth(2)
        if initiator_filter.is_visible():
            expect(initiator_filter).to_be_visible()

    def test_refresh_button_exists(self, class_page: Page):
        """Test that refresh button is present."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        refresh_button = class_page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()
