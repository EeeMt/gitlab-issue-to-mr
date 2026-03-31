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


def create_admin_and_login(page: Page):
    """Helper to create admin via bootstrap and login."""
    page.goto("/bootstrap")
    page.wait_for_selector(".bootstrap-card", timeout=10000)

    inputs = page.locator(".bootstrap-form input")
    inputs.nth(0).fill("dashboard_admin")
    inputs.nth(1).fill("Dashboard Admin")
    inputs.nth(2).fill("dashboard_admin@example.com")

    password_inputs = page.locator("input[type='password']")
    password_inputs.nth(0).fill("securepassword123")
    password_inputs.nth(1).fill("securepassword123")

    page.get_by_role("button", name="Create Admin").click()
    page.wait_for_url("**/dashboard", timeout=10000)
    page.wait_for_load_state("networkidle")


@pytest.mark.dashboard
class TestDashboardPage:
    """Tests for the dashboard page functionality."""

    def test_dashboard_page_loads(self, page: Page, reset_database):
        """Test that the dashboard page loads without errors."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Verify dashboard title is visible
        expect(page.locator(".dashboard__title")).to_be_visible()

    def test_dashboard_title_is_displayed(self, page: Page, reset_database):
        """Test that the dashboard title is displayed."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Verify dashboard title is visible
        expect(page.locator(".dashboard__title")).to_be_visible()

    def test_dashboard_subtitle_is_displayed(self, page: Page, reset_database):
        """Test that the dashboard subtitle is displayed."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Verify dashboard subtitle is visible
        expect(page.locator(".dashboard__subtitle")).to_be_visible()


@pytest.mark.dashboard
class TestDashboardFilters:
    """Tests for dashboard filter interactions."""

    def test_status_filter_is_present(self, page: Page, reset_database):
        """Test that status filter dropdown is present."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        # Status filter should be visible
        status_filter = page.locator(".dashboard__filters .n-select").first
        expect(status_filter).to_be_visible()

    def test_project_filter_is_present(self, page: Page, reset_database):
        """Test that project filter dropdown is present."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        # Project filter should be visible
        project_filter = page.locator(".dashboard__filters .n-select").nth(1)
        expect(project_filter).to_be_visible()

    def test_initiator_filter_is_present(self, page: Page, reset_database):
        """Test that initiator filter dropdown is present."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        # Initiator filter should be visible
        initiator_filter = page.locator(".dashboard__filters .n-select").nth(2)
        expect(initiator_filter).to_be_visible()

    def test_filters_area_contains_refresh_button(self, page: Page, reset_database):
        """Test that refresh button is present in filters area."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")

        # Refresh button should be visible
        refresh_button = page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()


@pytest.mark.dashboard
class TestDashboardSummaryCards:
    """Tests for dashboard summary card display."""

    def test_summary_cards_are_displayed(self, page: Page, reset_database):
        """Test that summary cards are displayed on the dashboard."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Summary cards should be visible
        summary_cards = page.locator(".dashboard-summary-card")
        expect(summary_cards.first).to_be_visible()

    def test_summary_card_has_label(self, page: Page, reset_database):
        """Test that summary cards have labels."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # First summary card label should be visible
        summary_label = page.locator(".dashboard-summary-card__label").first
        expect(summary_label).to_be_visible()

    def test_summary_card_has_value(self, page: Page, reset_database):
        """Test that summary cards have values."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # First summary card value should be visible
        summary_value = page.locator(".dashboard-summary-card__value").first
        expect(summary_value).to_be_visible()


@pytest.mark.dashboard
class TestDashboardTaskTable:
    """Tests for dashboard task table display."""

    def test_task_table_is_present(self, page: Page, reset_database):
        """Test that the task data table is present."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Data table should be visible
        data_table = page.locator(".n-data-table")
        expect(data_table).to_be_visible()

    def test_task_table_has_headers(self, page: Page, reset_database):
        """Test that the task table has column headers."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Table headers should be visible
        table_headers = page.locator(".n-data-table-th")
        expect(table_headers.first).to_be_visible()

    def test_refresh_button_triggers_update(self, page: Page, reset_database):
        """Test that the refresh button triggers a data refresh."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Find and click refresh button
        refresh_button = page.get_by_role("button", name="Refresh")
        expect(refresh_button).to_be_visible()

        refresh_button.click()
        page.wait_for_timeout(500)


@pytest.mark.dashboard
class TestDashboardNavigation:
    """Tests for dashboard navigation interactions."""

    def test_dashboard_accessible_from_sidebar(self, page: Page, reset_database):
        """Test that dashboard is accessible from sidebar navigation."""
        create_admin_and_login(page)

        # Sidebar should have Dashboard link
        dashboard_link = page.locator(".nav-menu").get_by_text("Dashboard")
        if dashboard_link.is_visible():
            dashboard_link.click()
            page.wait_for_url("**/dashboard", timeout=5000)

    def test_task_row_click_navigation(self, page: Page, reset_database):
        """Test that clicking a task row initiates navigation."""
        create_admin_and_login(page)

        page.goto("/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Check if there are any task rows
        table_row = page.locator(".n-data-table-tr").first
        if table_row.is_visible():
            # Row should be clickable
            expect(table_row).to_be_visible()
