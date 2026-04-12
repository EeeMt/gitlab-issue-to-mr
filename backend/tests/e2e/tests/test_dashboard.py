"""
Dashboard E2E Tests

Tests for the Dashboard overview page including:
- Page loads and header displays
- Summary cards (4: Issues, Tasks, Running, Completed)
- Recent Issues section
- Running Tasks section
- New Issue button navigation
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.dashboard
class TestDashboardPage:
    """Tests for dashboard overview page layout."""

    def test_dashboard_page_loads(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("dashboard-page")).to_be_visible()

    def test_dashboard_header_is_displayed(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("dashboard-header")).to_be_visible()

    def test_dashboard_new_issue_button_visible(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("dashboard-new-issue-button")).to_be_visible()


@pytest.mark.dashboard
class TestDashboardSummaryCards:
    """Tests for dashboard summary cards."""

    def test_summary_section_visible(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_selector("[data-testid='dashboard-summary']", timeout=10000)
        expect(class_page.get_by_test_id("dashboard-summary")).to_be_visible()

    def test_summary_has_four_cards(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_selector("[data-testid='dashboard-summary']", timeout=10000)
        cards = class_page.get_by_test_id("dashboard-summary-card")
        assert cards.count() == 4

    def test_summary_cards_have_labels_and_values(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_selector("[data-testid='dashboard-summary']", timeout=10000)
        labels = class_page.locator(".summary-card__label")
        values = class_page.locator(".summary-card__value")
        expect(labels.first).to_be_visible()
        expect(values.first).to_be_visible()


@pytest.mark.dashboard
class TestDashboardSections:
    """Tests for dashboard content sections."""

    def test_recent_issues_section_visible(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("dashboard-recent-issues")).to_be_visible()

    def test_running_tasks_section_visible(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("dashboard-running-tasks")).to_be_visible()

    def test_recent_issues_has_data_table(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        table = class_page.get_by_test_id("dashboard-recent-issues").locator(".n-data-table")
        expect(table).to_be_visible()

    def test_running_tasks_has_data_table(self, class_page: Page):
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("domcontentloaded")
        table = class_page.get_by_test_id("dashboard-running-tasks").locator(".n-data-table")
        expect(table).to_be_visible()


@pytest.mark.dashboard
class TestDashboardNavigation:
    """Tests for dashboard navigation interactions."""

    def test_new_issue_button_navigates_to_create(self, logged_in_page: Page):
        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.get_by_test_id("dashboard-new-issue-button").click()
        logged_in_page.wait_for_url("**/issues/create", timeout=5000)
        assert "/issues/create" in logged_in_page.url

    def test_root_redirects_to_dashboard(self, class_page: Page):
        class_page.goto("/")
        class_page.wait_for_url("**/dashboard", timeout=10000)
        assert "/dashboard" in class_page.url
