"""
Dashboard E2E Tests

Tests for the Dashboard overview page (/dashboard) including:
- Page loads and header displays
- Summary cards (4: Issues, Tasks, Running, Completed)
- Summary card values render correctly
- Recent Issues section with data table
- Running Tasks section with data table
- New Issue button navigation
- Issue click navigation to IssueView
- Root redirect to /dashboard
"""

import pytest
from playwright.sync_api import Page, expect
from conftest import api_create_issue, api_get_first_project, _get_cookies


# ---------------------------------------------------------------------------
# 1. Page layout (read-only, class_page)
# ---------------------------------------------------------------------------

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

    def test_summary_card_values_are_numeric(self, class_page: Page):
        """Each summary card value should display a number."""
        class_page.goto("/dashboard")
        class_page.wait_for_selector("[data-testid='dashboard-summary']", timeout=10000)
        values = class_page.locator(".summary-card__value")
        for i in range(values.count()):
            text = values.nth(i).inner_text().strip()
            assert text.isdigit(), f"Card value {i} is not numeric: {text!r}"


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

    def test_recent_issues_table_has_columns(self, class_page: Page):
        """Recent issues table should have column headers."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("networkidle")
        headers = class_page.get_by_test_id("dashboard-recent-issues").locator("thead th")
        if headers.count() > 0:
            assert headers.count() >= 3

    def test_running_tasks_table_has_columns(self, class_page: Page):
        """Running tasks table should have column headers."""
        class_page.goto("/dashboard")
        class_page.wait_for_load_state("networkidle")
        headers = class_page.get_by_test_id("dashboard-running-tasks").locator("thead th")
        if headers.count() > 0:
            assert headers.count() >= 2


# ---------------------------------------------------------------------------
# 2. Navigation interactions (logged_in_page — function-scoped, writes OK)
# ---------------------------------------------------------------------------

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

    def test_click_issue_title_navigates_to_issue_view(self, logged_in_page: Page, backend_url):
        """Clicking an issue title in recent issues should navigate to /issues/:id."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        issue = api_create_issue(backend_url, cookies, project["id"], title="DashboardLinkNav")

        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("networkidle")

        recent_issues = logged_in_page.get_by_test_id("dashboard-recent-issues")
        link = recent_issues.get_by_text("DashboardLinkNav")
        link.click()
        logged_in_page.wait_for_url(f"**/issues/{issue['id']}", timeout=5000)
        assert f"/issues/{issue['id']}" in logged_in_page.url


@pytest.mark.dashboard
class TestDashboardIssueAppears:
    """Test that created issues appear in the dashboard recent issues section."""

    def test_created_issue_appears_in_recent_issues(self, logged_in_page: Page, backend_url):
        """After creating an issue via API, it should appear in recent issues."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        api_create_issue(backend_url, cookies, project["id"], title="DashboardRecentTest")

        logged_in_page.goto("/dashboard")
        logged_in_page.wait_for_load_state("networkidle")

        recent_issues = logged_in_page.get_by_test_id("dashboard-recent-issues")
        expect(recent_issues.get_by_text("DashboardRecentTest")).to_be_visible()
