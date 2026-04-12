"""
Issue List E2E Tests

Tests for the Issue List page (/issues) including:
- Page loads and layout
- Create button navigation
- Status filter visible and functional
- Project filter visible
- Issue click navigation to IssueView
- Created issue appears in list
- Status tag rendering
"""

import pytest
from playwright.sync_api import Page, expect
from conftest import api_create_issue, api_get_first_project, _get_cookies


# ---------------------------------------------------------------------------
# 1. Page layout (read-only, class_page)
# ---------------------------------------------------------------------------

@pytest.mark.issue_list
class TestIssueListPage:
    """Tests for issue list page layout."""

    def test_issue_list_page_loads(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-page")).to_be_visible()

    def test_issue_list_header_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-header")).to_be_visible()

    def test_issue_list_table_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-table")).to_be_visible()

    def test_create_button_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-create-button")).to_be_visible()

    def test_status_filter_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        expect(class_page.get_by_test_id("issue-list-status-filter")).to_be_visible()

    def test_project_filter_visible(self, class_page: Page):
        class_page.goto("/issues")
        class_page.wait_for_load_state("domcontentloaded")
        filters = class_page.locator(".issue-list__filter--project")
        expect(filters).to_be_visible()

    def test_table_has_expected_columns(self, class_page: Page):
        """Issue table should have column headers."""
        class_page.goto("/issues")
        class_page.wait_for_load_state("networkidle")
        table = class_page.get_by_test_id("issue-list-table")
        headers = table.locator("thead th")
        expect(headers.first).to_be_visible(timeout=5000)
        assert headers.count() >= 4


# ---------------------------------------------------------------------------
# 2. Navigation + data interactions (logged_in_page)
# ---------------------------------------------------------------------------

@pytest.mark.issue_list
class TestIssueListNavigation:
    """Tests for issue list navigation."""

    def test_create_button_navigates_to_create_issue(self, logged_in_page: Page):
        logged_in_page.goto("/issues")
        logged_in_page.wait_for_load_state("domcontentloaded")
        logged_in_page.get_by_test_id("issue-list-create-button").click()
        logged_in_page.wait_for_url("**/issues/create", timeout=5000)
        assert "/issues/create" in logged_in_page.url

    def test_click_issue_title_navigates_to_issue_view(self, logged_in_page: Page, backend_url):
        """Clicking an issue title should navigate to /issues/:id."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        issue = api_create_issue(backend_url, cookies, project["id"], title="IssueListClickNav")

        logged_in_page.goto("/issues")
        logged_in_page.wait_for_load_state("networkidle")

        table = logged_in_page.get_by_test_id("issue-list-table")
        link = table.get_by_text("IssueListClickNav")
        expect(link).to_be_visible(timeout=10000)
        link.click()
        logged_in_page.wait_for_url(f"**/issues/{issue['id']}", timeout=5000)
        assert f"/issues/{issue['id']}" in logged_in_page.url


@pytest.mark.issue_list
class TestIssueListData:
    """Tests that issue list shows correct data."""

    def test_created_issue_appears_in_list(self, logged_in_page: Page, backend_url):
        """After creating an issue via API, it should appear in the list."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        api_create_issue(backend_url, cookies, project["id"], title="IssueListAppear")

        logged_in_page.goto("/issues")
        logged_in_page.wait_for_load_state("networkidle")

        table = logged_in_page.get_by_test_id("issue-list-table")
        expect(table.get_by_text("IssueListAppear")).to_be_visible(timeout=10000)

    def test_issue_shows_status_tag(self, logged_in_page: Page, backend_url):
        """New issue should display a status tag."""
        cookies = _get_cookies(logged_in_page)
        project = api_get_first_project(backend_url, cookies)
        api_create_issue(backend_url, cookies, project["id"], title="IssueStatusTag")

        logged_in_page.goto("/issues")
        logged_in_page.wait_for_load_state("networkidle")

        table = logged_in_page.get_by_test_id("issue-list-table")
        tags = table.locator(".n-tag")
        assert tags.count() > 0


@pytest.mark.issue_list
class TestIssueListFilters:
    """Tests for issue list filter functionality."""

    def test_status_filter_opens_dropdown(self, logged_in_page: Page):
        """Status filter should open a dropdown with options."""
        logged_in_page.goto("/issues")
        logged_in_page.wait_for_load_state("domcontentloaded")

        filter_el = logged_in_page.get_by_test_id("issue-list-status-filter")
        filter_el.locator(".n-base-selection").click()
        logged_in_page.wait_for_timeout(500)

        options = logged_in_page.locator(".n-base-select-option")
        assert options.count() >= 3  # open, in_progress, completed, closed
